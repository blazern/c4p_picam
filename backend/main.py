from datetime import datetime
from enum import Enum
import argparse
import git
import logging
import os
import psutil
import shutil
import signal
import subprocess
import sys
import time
import threading
import traceback
import yaml
import json
from zipfile import ZIP_STORED
import zipstream

try:
    import picamera
except ModuleNotFoundError:
    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
    print('!!! CANNOT IMPORT picamera - ALL WORK WITH CAMERA WILL FAIL !!!')
    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

from flask import Flask, url_for, Response, request
from markupsafe import escape

class VideoState:
    IDLE = 'idle'
    PREVIEW = 'previewing'
    RECORDING = 'recording'
    INSUFFICIENT_STORAGE = 'insufficient storage'

class Bitrate:
    def __init__(self, description, name, value):
        self.description = description
        self.name = name
        self.value = value

class Bitrates(Enum):
    MBIT_1 = Bitrate('1 Mbit/s (YouTube 480p)', '1', 1000000)
    MBIT_2_5 = Bitrate('2.5 Mbit/s (YouTube 720p)', '2.5', 2500000)
    MBIT_4_5 = Bitrate('4.5 Mbit/s (YouTube 1080p)', '4.5', 4500000)
    @staticmethod
    def from_name(name):
        for bitrate in list(Bitrates):
            if bitrate.value.name == name:
                return bitrate
        raise ValueError('Could not find a bitrate with short name {}'.format(name))

class State:
    video_state = VideoState.IDLE
    recording_camera = None
    stopping_video_preview = False
    stopping_video_recording = False
    previewing_thread = None
    recording_thread = None

    def cleanup_previewing_state(self):
        self.previewing_thread = None
        self.stopping_video_preview = False
        self.video_state = VideoState.IDLE

    def cleanup_recording_state(self):
        self.recording_thread = None
        self.stopping_video_recording = False
        self.video_state = VideoState.IDLE
        if self.recording_camera:
            self.recording_camera.stop_recording()
        self.recording_camera = None

class Config:
    video_preview_url = None
    video_preview_cmd = None

MIN_SYSTEM_FREE_SPACE = 100 * 1024 * 1024 # 100 megabytes
BACKGROUND_TASKS_TIMEOUT_SECS = 10
STATE = State()
CONFIG = Config()
# The server uses complex in-memory state and therefore cannot simply serve
# multiple requests simultaneously.
# But at the same time there're long operation which must not block the server
# (currently there's only 1 such an operation - videos downloading).
# As a good compromise the server allows only 1 process but multiple threads,
# and all short operations use LOCK to dissallow their async calls.
LOCK = threading.Lock()
app = Flask(__name__)

####################################################################
################################HTTP################################
####################################################################
@app.route('/global_state')
def global_state():
    with LOCK:
        # It's a good time to verify that background threads are still alive!
        if STATE.video_state == VideoState.PREVIEW:
            if not STATE.previewing_thread or not STATE.previewing_thread.is_alive():
                logging.error('Previeing fail detected, cleaning up')
                STATE.cleanup_previewing_state()
        if STATE.video_state == VideoState.RECORDING:
            if not STATE.recording_thread or not STATE.recording_thread.is_alive():
                logging.error('Recording fail detected, cleaning up')
                STATE.cleanup_recording_state()

        supported_bitrates = list(
            map(lambda b: (b.value.__dict__), list(Bitrates)))

        state = {
            'video_preview_url': CONFIG.video_preview_url,
            'video_state': STATE.video_state,
            'free_space_bytes': system_free_space(),
            'recorded_videos_size_bytes': get_size_of(recorded_videos_folder()),
            'bitrate': STATE.bitrate.name,
            'supported_bitrates': supported_bitrates
        }
        return result_to_json(state)

@app.route('/set_bitrate')
def set_bitrate():
    with LOCK:
        if STATE.video_state == VideoState.RECORDING:
            return error_to_json('Cannot change bitrate while recording')
        input_bitrate = request.args.get('bitrate')
        STATE.bitrate = Bitrates.from_name(input_bitrate).value
        return result_to_json('ok')

@app.route('/start_video_preview')
def start_video_preview():
    with LOCK:
        if STATE.video_state == VideoState.PREVIEW:
            return result_to_json('ok')
        elif STATE.video_state == VideoState.RECORDING:
            return error_to_json('cannot preview while recording in progress')

        def thread_function():
            STATE.video_state = VideoState.PREVIEW
            while not STATE.stopping_video_preview:
                logging.info('Starting video preview by {}'.format(CONFIG.video_preview_cmd))
                proc = subprocess.Popen(CONFIG.video_preview_cmd,
                                        stdout=subprocess.PIPE,
                                        shell=True,
                                        preexec_fn=os.setsid)
                while True:
                    time.sleep(1)
                    if proc.poll() is not None:
                        logging.info('Video preview process has died - restarting')
                        break
                    if STATE.stopping_video_preview:
                        logging.info('Stopping video preview')
                        if proc.poll() is None:
                            logging.info('Sending SIGTERM signal to video preview')
                            # Kill the process if it's still alive
                            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                            time.sleep(3)
                            if proc.poll() is None:
                                logging.info('Sending SIGKILL signal to video preview')
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        break
            STATE.cleanup_previewing_state()
            logging.info('Video preview stopped')

        STATE.previewing_thread = threading.Thread(target=thread_function)
        STATE.previewing_thread.start()

        if not poll(success_fn = lambda: STATE.video_state == VideoState.PREVIEW,
                    operation_thread = STATE.previewing_thread,
                    operation_name = 'previewing start'):
            STATE.cleanup_previewing_state()
            return error_to_json('couldn\'t start previewing')
        return result_to_json('ok')

@app.route('/stop_video_preview')
def stop_video_preview():
    with LOCK:
        result = result_to_json('ok')
        if STATE.video_state == VideoState.PREVIEW:
            STATE.stopping_video_preview = True
            if not poll(success_fn = lambda: STATE.video_state != VideoState.PREVIEW,
                        operation_thread = STATE.previewing_thread,
                        operation_name = 'previewing stop'):
                result = error_to_json('couldn\'t stop previewing')
        STATE.cleanup_previewing_state()
        return result

@app.route('/delete_recorded_videos')
def delete_recorded_videos():
    with LOCK:
        if STATE.video_state == VideoState.RECORDING:
            return error_to_json('cannot remove recorded videos during recording')
        path = recorded_videos_folder()
        if os.path.exists(path) and os.path.isdir(path):
            shutil.rmtree(path)
        return result_to_json('ok')

@app.route('/start_video_recording')
def start_video_recording():
    with LOCK:
        def is_enough_free_space():
            return MIN_SYSTEM_FREE_SPACE < system_free_space()

        if STATE.video_state == VideoState.PREVIEW:
            return error_to_json('cannot record while previewing in progress')
        elif STATE.video_state == VideoState.RECORDING:
            return result_to_json('ok')
        elif not is_enough_free_space():
            return error_to_json('not enough of free space')

        def now_str():
            return datetime.now().strftime("%Y_%m_%d__%H_%M_%S")

        # A function for background thread which is used mostly for retry logic.
        # Retry logic is needed because video recording is the main function of this script
        # and it's needed to be as robust as possible.
        def thread_function():
            logging.info('Starting video recording thread')
            retry_timeout = 1
            # While recording state is not forgatten and we're not asked to stop
            while STATE.recording_thread and not STATE.stopping_video_recording:
                try:
                    with picamera.PiCamera() as camera:
                        STATE.recording_camera = camera
                        # Note: we change state only when we obained the camera
                        # object because it's a fatal scenario when during recording
                        # start camera object cannot be obtained.
                        # The main thread must not respond with a success msg in such
                        # a scenario.
                        STATE.video_state = VideoState.RECORDING
                        perform_recording()
                except Exception as e:
                    critical_error('Caught exception while trying to perform recording: {}'.format(e))
                    logging.error('Caught exception stacktrace: \n{}'.format(traceback.format_exc()))
                    logging.info('Retrying recording in {} sec(s)'.format(retry_timeout))
                    time.sleep(retry_timeout)
                    retry_timeout = min(retry_timeout * 2, 60) # x2 or 1 minute
            logging.info('Video recording thread stopped')

        # The actual recording
        def perform_recording():
            last_video_name = os.path.join(
                recorded_videos_folder(),
                '{}.h264'.format(now_str()))
            logging.info('Starting recording of {} with bitrate {}'
                .format(last_video_name, STATE.bitrate.name))

            STATE.recording_camera.start_recording(last_video_name, bitrate=STATE.bitrate.value)
            last_recoring_start_time = datetime.now()

            while is_enough_free_space() and not STATE.stopping_video_recording:
                STATE.recording_camera.wait_recording(1)
                passed_time = (datetime.now() - last_recoring_start_time).total_seconds()

                if CONFIG.recorded_videos_length_seconds < passed_time:
                    new_video_name = os.path.join(
                        recorded_videos_folder(),
                        '{}.h264'.format(now_str()))
                    logging.info('Stopping recording of {}, starting recording of {}'
                        .format(last_video_name, new_video_name))
                    STATE.recording_camera.split_recording(new_video_name)
                    last_recoring_start_time = datetime.now()
            STATE.cleanup_recording_state()

        STATE.recording_thread = threading.Thread(target=thread_function)
        STATE.recording_thread.start()
        if not poll(success_fn = lambda: STATE.video_state == VideoState.RECORDING,
                    operation_thread = STATE.recording_thread,
                    operation_name = 'recording start'):
            STATE.cleanup_recording_state()
            return error_to_json('couldn\'t start recording')

        return result_to_json('ok')

@app.route('/stop_video_recording')
def stop_video_recording():
    with LOCK:
        result = result_to_json('ok')
        if STATE.video_state == VideoState.RECORDING:
            STATE.stopping_video_recording = True
            if not poll(success_fn = lambda: STATE.video_state != VideoState.RECORDING,
                        operation_thread = STATE.recording_thread,
                        operation_name = 'recording stop'):
                result = error_to_json('couldn\'t stop recording')
        STATE.cleanup_recording_state()
        return result

@app.route('/download_all_recordings')
def download_all_recordings():
    # NOTE: even though the LOCK is used here, we give the create Response object a stream generator,
    # which is not locked, and therefore server's clients can use other commands while they download
    # videos.
    with LOCK:
        def generate_zip():
            stream = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED, allowZip64=True)
            for filename in os.listdir(recorded_videos_folder()):
                path = os.path.join(recorded_videos_folder(), filename)
                if os.path.isdir(path):
                    continue
                stream.write(path, arcname=filename, compress_type=ZIP_STORED)
                yield from stream.flush()
            yield from stream
        response = Response(generate_zip(), mimetype='application/zip')
        response.headers['Content-Disposition'] = 'attachment; filename={}'.format('recordings.zip')
        return response

@app.route('/update_source_code')
def update_source_code():
    repo = git.Repo('./..')
    old_head = repo.head.commit
    pulled = repo.remotes.origin.pull()
    new_head = repo.head.commit
    if old_head != new_head:
        return result_to_json('updated')
    else:
        return result_to_json('up-to-date')

####################################################################
################################HTTP################################
####################################################################

# Returns True if success_fn()==True
# Returns False if timed out OR operation_thread.is_alive()==False
def poll(success_fn, operation_thread, operation_name):
    waiting_start = datetime.now()
    while not success_fn():
        # Note: we double check for success because of threading
        if not operation_thread.is_alive() and not success_fn():
            critical_error('Thread of `{}` is dead but the operation was not successful'.format(operation_name))
            # success_fn() == False but the thread is Dead - operation has failed
            return False
        if BACKGROUND_TASKS_TIMEOUT_SECS < (datetime.now() - waiting_start).total_seconds():
            if operation_thread.is_alive():
                critical_error('Operation `{}` timed out but its thread is still alive'.format(operation_name))
            return False
        logging.info('Waiting for `{}`...'.format(operation_name))
        time.sleep(1)
    return True

# Note that we do not crash on critical errors because the script must
# be as robust as possible and try to recover even from critical errors.
def critical_error(error):
    error_msg = '!! ' + error + ' !!'
    logging.error('!' * len(error_msg))
    logging.error(error_msg)
    logging.error('!' * len(error_msg))

def result_to_json(result):
    return create_response_for(json.dumps({ 'result': result }))

def error_to_json(error):
    return create_response_for(json.dumps({ 'error': error }))

def create_response_for(string):
    resp = Response(string)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'max-age=0'
    return resp

def get_size_of(path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size

def system_free_space():
    return psutil.disk_usage('/').free

def recorded_videos_folder():
    path = CONFIG.recorded_videos_folder
    os.makedirs(path, exist_ok=True)
    return path


def main(argv):
    logging.getLogger().setLevel(logging.INFO)
    if sys.version_info[0] == 2:
        sys.exit('Only Python 3 is supported')

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True,
                        help='Host used for the server. '
                        + 'Most likely you want to specify its IP in local network.')
    parser.add_argument('--port', required=True,
                        help='Port used for the server.', type=int)
    parser.add_argument('--video-preview-cmd', required=True,
                        help='System command which will be used to start video preview. '
                        + 'Most likely it\'s a "mjpg-streamer" cmd. '
                        + 'For manual testing you can use "while true; do date; sleep 2; done > /tmp/atata"')
    parser.add_argument('--video-preview-url', required=True,
                        help='Video preview URL which will be put into an <iframe> on frontend. '
                        + 'For manual testing you can use any URL.')
    parser.add_argument('--recorded-videos-folder', required=True)
    parser.add_argument('--recorded-videos-length-seconds', type=int, default=600)
    parser.add_argument('--bitrate', choices=list(map(lambda b: b.value.name, list(Bitrates))),
                        default=Bitrates.MBIT_2_5.value.name,
                        help='Bitrate of recorded videos in Mbit/s')
    options = parser.parse_args()

    CONFIG.video_preview_url = options.video_preview_url
    CONFIG.video_preview_cmd = options.video_preview_cmd
    CONFIG.recorded_videos_folder = options.recorded_videos_folder
    CONFIG.recorded_videos_length_seconds = options.recorded_videos_length_seconds
    STATE.bitrate = Bitrates.from_name(options.bitrate).value

    # See LOCK description for info about process=1
    app.run(host=options.host, port=options.port, threaded=True, processes=1)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    finally:
        stop_video_preview()
