from datetime import datetime
from enum import Enum
import argparse
import logging
import os
import psutil
import shutil
import signal
import subprocess
import sys
import time
import threading
import yaml
import json

try:
    import picamera
except ModuleNotFoundError:
    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
    print('!!! CANNOT IMPORT picamera - ALL WORK WITH CAMERA WILL FAIL !!!')
    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

from flask import Flask, url_for, Response
from markupsafe import escape

class VideoState:
    IDLE = 'idle'
    PREVIEW = 'previewing'
    RECORDING = 'recording'
    INSUFFICIENT_STORAGE = 'insufficient storage'

class State:
    video_state = VideoState.IDLE
    stopping_video_preview = False
    stopping_video_recording = False

class Config:
    video_preview_url = None
    video_preview_cmd = None

MIN_SYSTEM_FREE_SPACE = 100 * 1024 * 1024 # 100 megabytes
STATE = State()
CONFIG = Config()
app = Flask(__name__)

####################################################################
################################HTTP################################
####################################################################
@app.route('/video_preview_url')
def video_preview_url():
    return result_to_json(CONFIG.video_preview_url)

@app.route('/video_state')
def video_state():
    return result_to_json(STATE.video_state)

@app.route('/start_video_preview')
def start_video_preview():
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
        STATE.stopping_video_preview = False
        STATE.video_state = VideoState.IDLE
        logging.info('Video preview stopped')

    thread = threading.Thread(target=thread_function)
    thread.start()

    while not STATE.video_state == VideoState.PREVIEW:
        logging.info('Waiting for video preview start...')
        time.sleep(1)

    return result_to_json('ok')

@app.route('/stop_video_preview')
def stop_video_preview():
    if STATE.video_state == VideoState.PREVIEW:
        STATE.stopping_video_preview = True
        while STATE.video_state == VideoState.PREVIEW:
            logging.info('Waiting for video preview stop...')
            time.sleep(1)
    return result_to_json('ok')

@app.route('/free_space_bytes')
def free_space_bytes():
    return result_to_json(system_free_space())

@app.route('/recorded_videos_size_bytes')
def recorded_videos_size_bytes():
    return result_to_json(get_size_of(recorded_videos_folder()))

@app.route('/delete_recorded_videos')
def delete_recorded_videos():
    if STATE.video_state == VideoState.RECORDING:
        return error_to_json('cannot remove recorded videos during recording')
    path = recorded_videos_folder()
    if os.path.exists(path) and os.path.isdir(path):
        shutil.rmtree(path)
    return result_to_json('ok')

# TODO: this function needs to be as robust as it's possible -
#       if recording fails, it needs to be restarted automatically.
@app.route('/start_video_recording')
def start_video_recording():
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

    def thread_function():
        logging.info('Starting video recording')
        with picamera.PiCamera() as camera:
            STATE.video_state = VideoState.RECORDING
            # camera.resolution = (640, 480)
            last_video_name = os.path.join(
                recorded_videos_folder(),
                '{}.h264'.format(now_str()))
            logging.info('Starting recording of {}'.format(last_video_name))
            camera.start_recording(last_video_name)
            last_recoring_start_time = datetime.now()

            while is_enough_free_space() and not STATE.stopping_video_recording:
                camera.wait_recording(1)
                passed_time = (datetime.now() - last_recoring_start_time).total_seconds()
                if CONFIG.recorded_videos_length_seconds < passed_time:
                    new_video_name = os.path.join(
                        recorded_videos_folder(),
                        '{}.h264'.format(now_str()))
                    logging.info('Stopping recording of {}, starting recording of {}'
                        .format(last_video_name, new_video_name))
                    camera.split_recording(new_video_name)
                    last_recoring_start_time = datetime.now()
            camera.stop_recording()
        STATE.stopping_video_recording = False
        STATE.video_state = VideoState.IDLE
        logging.info('Video recording stopped')

    thread = threading.Thread(target=thread_function)
    thread.start()

    while not STATE.video_state == VideoState.RECORDING:
        logging.info('Waiting for video recording start...')
        time.sleep(1)
    return result_to_json('ok')

@app.route('/stop_video_recording')
def stop_video_recording():
    if STATE.video_state == VideoState.RECORDING:
        STATE.stopping_video_recording = True
        while STATE.video_state == VideoState.RECORDING:
            logging.info('Waiting for video recording stop...')
            time.sleep(1)
    return result_to_json('ok')
####################################################################
################################HTTP################################
####################################################################


def result_to_json(result):
    return create_response_for(json.dumps({ 'result': result }))

def error_to_json(error):
    return create_response_for(json.dumps({ 'error': error }))

def create_response_for(string):
    resp = Response(string)
    resp.headers['Access-Control-Allow-Origin'] = '*'
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
    parser.add_argument('--recorded-videos-length-seconds', type=int, default=300)
    options = parser.parse_args()

    CONFIG.video_preview_url = options.video_preview_url
    CONFIG.video_preview_cmd = options.video_preview_cmd
    CONFIG.recorded_videos_folder = options.recorded_videos_folder
    CONFIG.recorded_videos_length_seconds = options.recorded_videos_length_seconds

    # Single process and single thread so that it would be easier to handle requests.
    # And also because there's expected to be no more than a couple of clients (preferrably 1).
    app.run(host=options.host, port=options.port, threaded=False, processes=1)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    finally:
        stop_video_preview()
