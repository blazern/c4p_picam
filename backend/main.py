from enum import Enum
import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import threading
import yaml
import json

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

class Config:
    video_preview_url = None
    video_preview_cmd = None

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
    options = parser.parse_args()

    CONFIG.video_preview_url = options.video_preview_url
    CONFIG.video_preview_cmd = options.video_preview_cmd

    # Single process and single thread so that it would be easier to handle requests.
    # And also because there's expected to be no more than a couple of clients (preferrably 1).
    app.run(host=options.host, port=options.port, threaded=False, processes=1)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    finally:
        stop_video_preview()
