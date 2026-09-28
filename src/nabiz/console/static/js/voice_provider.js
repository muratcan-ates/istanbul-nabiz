// Capability hints for P04-kart. This module never starts capture or sends audio.
export function voiceCapabilities(scope = globalThis) {
  const browser = scope.window || scope;
  const navigator = browser.navigator || {};
  return {
    browserRecognition: Boolean(browser.SpeechRecognition || browser.webkitSpeechRecognition),
    browserSynthesis: Boolean(browser.speechSynthesis),
    microphone: Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
  };
}

export function speechPath(serverAvailable, capabilities) {
  if (serverAvailable && capabilities.microphone) return 'provider';
  if (capabilities.browserRecognition) return 'browser';
  return 'typing';
}

export function syntheticVoiceNotice(language = 'tr') {
  return language === 'en'
    ? 'This voice is synthetic. You can continue by typing.'
    : 'Bu ses yapaydır. Yazarak devam edebilirsiniz.';
}
