import axios from 'axios';
import React from 'react';
import Cookies from 'universal-cookie';

import './App.css';
import { config } from './config.js';


class App extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      showPreviewIframe: false,
      backendUrl: config.backendUrl
    }
    this.previewButtonClicked = this.previewButtonClicked.bind(this);
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
  }

  async setInitialState() {
    await this.updateVideoState();
    await this.updatePreviewUrl();
  }

  render() {
    let videoState = "Video state unknown";
    if (this.state.videoState) {
      videoState = this.state.videoState;
    }

    let previewButtonMessage;
    let previewIframe;
    if (this.state.showPreviewIframe) {
      previewButtonMessage = "Hide Video Preview";
      previewIframe = <div><iframe src={this.state.previewUrl} width={800} height={600}/></div>
    } else {
      previewButtonMessage = "Show Video Preview";
      previewIframe = "";
    }

    return (
      <div className="App">
      <header className="App-header">
        <form>
          <label>
            {'Backend address: '} 
            <input type="text" value={this.state.backendUrl} onChange={this.onBackendUrlChange} />
          </label>
        </form>
        <p> Video state: {videoState} </p>
        <p> <button disabled={!this.state.previewUrl} onClick={this.previewButtonClicked}> {previewButtonMessage}</button> </p>
        <p> {previewIframe} </p>
      </header>
    </div>
    );
  }

  async onBackendUrlChange(event) {
    this.cookies.set('backendUrl', event.target.value);
    await this.awaitableSetState({backendUrl: event.target.value});
    await this.setInitialState();
  }

  async updateVideoState() {
    try {
      const response = await axios.get(`${this.state.backendUrl}/video_state`);
      const videoState = response.data.result;
      this.setState({ videoState: videoState });
    } catch (err) {
      console.log(`Caught error: ${err}`);
      this.setState({ videoState: undefined });
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
    if (this.state.showPreviewIframe) {
      await this.hidePreview();
    } else {
      await this.showPreview();
    }
  }

  async showPreview() {
    if (this.state.showPreviewIframe) {
      return
    }
    try {
      const response = await axios.get(`${this.state.backendUrl}/start_video_preview`);
      const result = response.data.result;
      if (result === "ok") {
        await this.awaitableSetState({ showPreviewIframe: true });
        await this.updateVideoState()
      }
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }

  async hidePreview() {
    if (!this.state.showPreviewIframe) {
      return
    }
    try {
      const response = await axios.get(`${this.state.backendUrl}/stop_video_preview`);
      const result = response.data.result;
      if (result === "ok") {
        await this.awaitableSetState({ showPreviewIframe: false });
        await this.updateVideoState()
      }
    } catch (err) {
      console.log(`Caught error: ${err}`);
    }
  }
}

export default App;
