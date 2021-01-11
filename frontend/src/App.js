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
      supportedBitrates: [],
      loading: 0
    }
    this.previewButtonClicked = this.previewButtonClicked.bind(this);
    this.recordVideoButtonClicked = this.recordVideoButtonClicked.bind(this);
    this.onBackendUrlChange = this.onBackendUrlChange.bind(this);
    this.bitrateSelected = this.bitrateSelected.bind(this);
    this.downloadRecordingsClicked = this.downloadRecordingsClicked.bind(this);
    this.cookies = new Cookies();
  }

  async awaitableSetState(newState) {
    new Promise(resolve => this.setState(newState, resolve));
  }

  async componentDidMount() {
    if (this.cookies.get('backendUrl')) {
      await this.awaitableSetState({ 'backendUrl': this.cookies.get('backendUrl') });
    }
    await this.updateKnownBackendState();

    window.addEventListener('resize', this.updatePreviewSize.bind(this));

    this.periodicBackendStateUpdate();
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.updatePreviewSize.bind(this));
  }

  periodicBackendStateUpdate() {
    setTimeout(async () => {
      await this.updateKnownBackendState();
      this.periodicBackendStateUpdate()
    }, 10000)
  }

  updatePreviewSize() {
    this.setState({ previewWidth: window.innerWidth });
  }

  render() {
    let videoState = "Состояние неизвестно";
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
      previewButtonMessage = "Спрятать превью";
      const width = window.innerWidth;
      previewIframe = <div><iframe src={this.state.previewUrl} width={width} height={600} title="Video Preview"/></div>
    } else {
      previewButtonMessage = "Показать превью";
      previewIframe = "";
    }

    let recordButtonMessage;
    if (this.state.videoState === "recording") {
      recordButtonMessage = "Остановить запись";
    } else {
      recordButtonMessage = "Начать запись";
    }

    const enablePreview = this.state.videoState !== undefined
                          && this.state.videoState !== "recording"
                          && !this.state.loading;
    const enableRecording = this.state.videoState !== undefined
                          && !this.state.loading;
    const enableBitrateChange = this.state.videoState !== undefined
                          && this.state.videoState !== "recording"
                          && !this.state.loading;
    const enableRecordingsDownload = this.state.videoState !== undefined
                          && this.state.videoState !== "recording"
                          && !this.state.loading;

    let bitrateOptions = this.state.supportedBitrates.map((bitrate) =>
        <option
          key={bitrate.name}>
            {bitrate.description}
        </option>
    );
    let defaultBitrate;
    if (this.state.bitrate) {
      defaultBitrate = this.state.bitrate;
    } else if (this.state.supportedBitrates[0]) {
      defaultBitrate = this.state.supportedBitrates[0];
    } else {
      defaultBitrate = { description: 'N/A' }
    }

    return (
      <div className="App">
      <header className="App-header">
      <div className={this.state.loading ? 'LoaderDisplayed' : 'LoaderHidden'}>
        <Loader
          type="Puff"
          color="#00BFFF"/>
      </div>

      <div className="MainContent">
        <div className='Header'>Основное управление камерой.</div>
        <form>
          <label>
            {`Адрес backend'а: `}
            <input type="text" disabled={this.state.loading} value={this.state.backendUrl} onChange={this.onBackendUrlChange} />
          </label>
        </form>
        <button disabled={!enableRecordingsDownload} onClick={this.downloadRecordingsClicked}>Скачать записи</button>

        <p>
          <div className='Header'>Управление видео.</div>
          Состояние видео: {videoState} <br></br>
          Свободного места: {freeSpaceMegabytes}mb <br></br>
          Bitrate записи:
          <select
            value={defaultBitrate.description}
            disabled={!enableBitrateChange}
            onChange={this.bitrateSelected}>
              {bitrateOptions}
          </select>
        </p>
        <p>
          <button disabled={!enablePreview} onClick={this.previewButtonClicked}> {previewButtonMessage}</button>
          <button disabled={!enableRecording} onClick={this.recordVideoButtonClicked}> {recordButtonMessage}</button>
        </p>
      </div>
      <p> {previewIframe} </p>
    </header>
    </div>
    );
  }

  async onBackendUrlChange(event) {
    this.cookies.set('backendUrl', event.target.value);
    await this.awaitableSetState({ backendUrl: event.target.value });
    await this.updateKnownBackendState();
  }

  async bitrateSelected(event) {
    const newBitrate = this.state.supportedBitrates.find(b => b.description === event.target.value)
    try {
      const response = await axios.get(`${this.state.backendUrl}/set_bitrate?bitrate=${newBitrate.name}`);
      const result = response.data.result;
      if (result === "ok") {
        await this.updateKnownBackendState()
      }
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }

  async updateKnownBackendState() {
    try {
      const response = await axios.get(`${this.state.backendUrl}/global_state`);
      const result = response.data.result;
      const previewUrl = result.video_preview_url;
      const videoState = result.video_state;
      const freeSpaceBytes = result.free_space_bytes;

      const supportedBitrates = result.supported_bitrates;
      const bitrateName = result.bitrate;
      const bitrate = supportedBitrates.find(b => b.name === bitrateName);

      this.setState({
        previewUrl: previewUrl,
        videoState: videoState,
        freeSpaceBytes: freeSpaceBytes,
        bitrate: bitrate,
        supportedBitrates: supportedBitrates
      });
    } catch (err) {
      console.log(`Caught error: ${err}`);
      this.setState({
        previewUrl: '',
        videoState: undefined,
        freeSpaceBytes: 0,
        bitrate: undefined,
        supportedBitrates: []
      });
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

  downloadRecordingsClicked() {
    window.open(`${this.state.backendUrl}/download_all_recordings`)
  }
}

export default App;
