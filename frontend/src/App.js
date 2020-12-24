import axios from 'axios';
import Loader from 'react-loader-spinner'
import React from 'react';
import "react-loader-spinner/dist/loader/css/react-spinner-loader.css"
import Cookies from 'universal-cookie';

import './App.css';
import { config } from './config.js';


class App extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      backendUrl: config.backendUrl,
      previewWidth: window.innerWidth,
      loading: 0
    }
    this.previewButtonClicked = this.previewButtonClicked.bind(this);
    this.recordVideoButtonClicked = this.recordVideoButtonClicked.bind(this);
    this.onBackendUrlChange = this.onBackendUrlChange.bind(this);
    this.cookies = new Cookies();
  }

  async awaitableSetState(newState) {
    new Promise(resolve => this.setState(newState, resolve));
  }

  async componentDidMount() {
    if (this.cookies.get('backendUrl')) {
      await this.awaitableSetState({ 'backendUrl': this.cookies.get('backendUrl') });
    }
    await this.setInitialState();

    window.addEventListener('resize', this.updatePreviewSize.bind(this));
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.updatePreviewSize.bind(this));
  }

  updatePreviewSize() {
    this.setState({ previewWidth: window.innerWidth });
  }

  async setInitialState() {
    await this.updateKnownBackendState();
    await this.updatePreviewUrl();
  }

  render() {
    let videoState = "Video state unknown";
    if (this.state.videoState) {
      videoState = this.state.videoState;
    }
    let freeSpaceMegabytes = 0;
    if (this.state.freeSpaceBytes) {
      freeSpaceMegabytes = Number((this.state.freeSpaceBytes / 1024 / 1024).toFixed(0))
    }

    let previewButtonMessage;
    let previewIframe;
    if (this.state.videoState === 'previewing') {
      previewButtonMessage = "Hide Video Preview";
      const width = window.innerWidth;
      previewIframe = <div><iframe src={this.state.previewUrl} width={width} height={600} title="Video Preview"/></div>
    } else {
      previewButtonMessage = "Show Video Preview";
      previewIframe = "";
    }

    let recordButtonMessage;
    if (this.state.videoState === "recording") {
      recordButtonMessage = "Stop Video Recording";
    } else {
      recordButtonMessage = "Start Video Recording";
    }

    const enablePreview = this.state.videoState !== undefined
                          && this.state.videoState !== "recording";
    const enableRecording = this.state.videoState !== undefined;

    return (
      <div className="App">
      <header className="App-header">
      <div className={this.state.loading ? 'LoaderDisplayed' : 'LoaderHidden'}>
        <Loader
          type="Puff"
          color="#00BFFF"/>
      </div>
      <form>
        <label>
          {'Backend address: '}
          <input type="text" value={this.state.backendUrl} onChange={this.onBackendUrlChange} />
        </label>
      </form>
      <p> Video state: {videoState}, free space: {freeSpaceMegabytes}mb </p>
      <p>
        <button disabled={!enablePreview || this.state.loading} onClick={this.previewButtonClicked}> {previewButtonMessage}</button>
        <button disabled={!enableRecording || this.state.loading} onClick={this.recordVideoButtonClicked}> {recordButtonMessage}</button>
      </p>
      <p> {previewIframe} </p>
    </header>
    </div>
    );
  }

  async onBackendUrlChange(event) {
    this.cookies.set('backendUrl', event.target.value);
    await this.awaitableSetState({ backendUrl: event.target.value });
    await this.setInitialState();
  }

  async updateKnownBackendState() {
    try {
      const response1 = await axios.get(`${this.state.backendUrl}/video_state`);
      const videoState = response1.data.result;
      const response2 = await axios.get(`${this.state.backendUrl}/free_space_bytes`);
      const freeSpaceBytes = response2.data.result;
      this.setState({ videoState: videoState, freeSpaceBytes: freeSpaceBytes });
    } catch (err) {
      console.log(`Caught error: ${err}`);
      this.setState({ videoState: undefined, freeSpaceBytes: 0 });
    }
  }

  async updatePreviewUrl() {
    try {
      const response = await axios.get(`${this.state.backendUrl}/video_preview_url`);
      const previewUrl = response.data.result;
      this.setState({ previewUrl: previewUrl });
    } catch (err) {
      console.log(`Caught error: ${err}`);
      this.setState({ previewUrl: '' });
    }
  }

  async previewButtonClicked() {
    this.setState({ 'loading': this.state.loading + 1 })
    if (this.state.videoState !== 'previewing') {
      await this.showPreview();
    } else {
      await this.hidePreview();
    }
    this.setState({ 'loading': this.state.loading - 1 })
  }

  async showPreview() {
    try {
      const response = await axios.get(`${this.state.backendUrl}/start_video_preview`);
      const result = response.data.result;
      if (result === "ok") {
        await this.updateKnownBackendState()
      }
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }

  async hidePreview() {
    try {
      const response = await axios.get(`${this.state.backendUrl}/stop_video_preview`);
      const result = response.data.result;
      if (result === "ok") {
        await this.updateKnownBackendState()
      }
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }

  async recordVideoButtonClicked() {
    this.setState({ 'loading': this.state.loading + 1 })
    if (this.state.videoState !== 'recording') {
      if (this.state.videoState === 'previewing') {
        await this.hidePreview();
      }
      await this.startVideoRecording()
    } else {
      await this.stopVideoRecording()
    }
    this.setState({ 'loading': this.state.loading - 1 })
  }

  async startVideoRecording() {
    try {
      await axios.get(`${this.state.backendUrl}/start_video_recording`);
      await this.updateKnownBackendState()
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }

  async stopVideoRecording() {
    try {
      await axios.get(`${this.state.backendUrl}/stop_video_recording`);
      await this.updateKnownBackendState()
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }
}

export default App;
