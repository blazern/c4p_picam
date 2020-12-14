from enum import Enum
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


def init_config():
    config_env_var = 'C4P_BACKEND_CONFIG'
    config = os.environ[config_env_var]
    if config is None:
        sys.exit('An enviroment variable {} must be specified'.format(config_env_var))
    with open(config, 'r') as f:
        config = yaml.safe_load(f)
    for field in ['video_preview_cmd', 'video_preview_url']:
        if field not in config:
            sys.exit('Config field "{}" must be specified'.format(field))
    return config

def init_state():
    state = {}
    state.setdefault('video_state', VideoState.IDLE)
    state.setdefault('stopping_video_preview', False)
    return state

class VideoState:
    IDLE = 'idle'
    PREVIEW = 'previewing'
    RECORDING = 'recording'

CONFIG = init_config()
STATE = init_state()
app = Flask(__name__)


@app.route('/video_preview_url')
def video_preview_url():
    return result_to_json(CONFIG['video_preview_url'])

@app.route('/video_state')
def video_state():
    return result_to_json(STATE['video_state'])

@app.route('/start_video_preview')
def start_video_preview():
    if STATE['video_state'] == VideoState.PREVIEW:
        return result_to_json('ok')
    elif STATE['video_state'] == VideoState.RECORDING:
        return error_to_json('cannot preview while recording in progress')

    def thread_function():
        STATE['video_state'] = VideoState.PREVIEW
        while not STATE['stopping_video_preview']:
            logging.info('Starting video preview by {}'.format(CONFIG['video_preview_cmd']))
            proc = subprocess.Popen(CONFIG['video_preview_cmd'],
                                    stdout=subprocess.PIPE,
                                    shell=True,
                                    preexec_fn=os.setsid)
            while True:
                time.sleep(1)
                if proc.poll() is not None:
                    logging.info('Video preview process has died - restarting')
                    break
                if STATE['stopping_video_preview']:
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
        STATE['stopping_video_preview'] = False
        STATE['video_state'] = VideoState.IDLE
        logging.info('Video preview stopped')

    thread = threading.Thread(target=thread_function)
    thread.start()

    while not STATE['video_state'] == VideoState.PREVIEW:
        logging.info('Waiting for video preview start...')
        time.sleep(1)

    return result_to_json('ok')

@app.route('/stop_video_preview')
def stop_video_preview():
    if STATE['video_state'] == VideoState.PREVIEW:
        STATE['stopping_video_preview'] = True
        while STATE['video_state'] == VideoState.PREVIEW:
            logging.info('Waiting for video preview stop...')
            time.sleep(1)
    return result_to_json('ok')


def result_to_json(result):
    return create_response_for(json.dumps({ 'result': result }))

def error_to_json(error):
    return create_response_for(json.dumps({ 'error': error }))

def create_response_for(string):
    resp = Response(string)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

def main():
    logging.getLogger().setLevel(logging.INFO)
    if sys.version_info[0] == 2:
        sys.exit('Only Python 3 is supported')
    app.run(host='localhost', port=4321, threaded=False, processes=1)

if __name__ == "__main__":
    try:
        main()
    finally:
        stop_video_preview() 
