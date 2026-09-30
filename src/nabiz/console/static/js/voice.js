import { esc } from './format.js';

const DISCLOSURE = 'Sesle sormayı açarsanız sesiniz Nabız sunucusuna değil, tarayıcınızın konuşma tanıma sağlayıcısının sunucusuna (örneğin Google ya da Apple) gidebilir. Nabız ses kaydı tutmaz; yalnız ekranda onayladığınız metin gönderilir.';

function pickVoice(voices) {
  return voices.find((voice) => voice.lang === 'tr-TR')
    || voices.find((voice) => (voice.lang || '').startsWith('tr'))
    || null;
}

function recognitionMessage(code) {
  const messages = {
    'not-allowed': 'Mikrofon izni verilmedi; yazarak sorabilirsiniz.',
    'no-speech': 'Ses algılanmadı.',
    'audio-capture': 'Mikrofon bulunamadı.',
    network: 'Ses hizmetine ulaşılamadı; yazarak sorabilirsiniz.',
  };
  return messages[code] || 'Ses alınamadı; yazarak sorabilirsiniz.';
}

function confirmPrompt(transcript) {
  return `Sizi şöyle anladım: "${transcript}"`;
}

function mountVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const synth = 'speechSynthesis' in window;
  if (!Recognition && !synth) return;

  const form = document.getElementById('chat-form');
  const row = form && form.querySelector('.chat-row');
  const input = document.getElementById('chat-input');
  const submit = document.getElementById('chat-submit');
  const log = document.getElementById('chat-log');
  if (!form || !row || !input || !submit) return;

  const stylesheet = document.createElement('link');
  stylesheet.id = 'voice-css';
  stylesheet.rel = 'stylesheet';
  stylesheet.href = '/css/voice.css';
  document.head.appendChild(stylesheet);

  const region = document.createElement('div');
  region.className = 'voice';
  region.id = 'voice';

  const disclosure = document.createElement('p');
  disclosure.id = 'voice-disclosure';
  disclosure.className = 'voice-disclosure';
  disclosure.textContent = DISCLOSURE;

  const optIn = document.createElement('button');
  optIn.type = 'button';
  optIn.className = 'btn';
  optIn.id = 'voice-optin';
  optIn.setAttribute('aria-pressed', 'false');
  optIn.setAttribute('aria-describedby', 'voice-disclosure');
  optIn.textContent = 'Sesle sormayı aç';

  const status = document.createElement('p');
  status.className = 'sr-only';
  status.id = 'voice-status';
  status.setAttribute('role', 'status');

  region.append(disclosure, optIn, status);
  const toolsSlot = document.getElementById('composer-tools'); if (toolsSlot) toolsSlot.append(region); else form.after(region);

  let talkButton = null;
  let preview = null;
  let confirmation = null;
  let readButton = null;
  let stopButton = null;
  let recognition = null;
  let selectedVoice = null;
  let readingEnabled = false;
  let observer = null;
  let utterance = null;
  let voicesChanged = null;
  const readMessages = new WeakSet();
  const noVoiceMessage = 'Bu tarayıcıda Türkçe ses yok; okuma kapalı.';

  function say(message) {
    status.textContent = message;
  }

  function resetTalkButton() {
    if (!talkButton) return;
    talkButton.setAttribute('aria-pressed', 'false');
    talkButton.textContent = 'Bas, konuş';
  }

  function removeConfirmation() {
    if (!confirmation) return;
    confirmation.remove();
    confirmation = null;
  }

  function focusInput() {
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }

  function createConfirmation() {
    const panel = document.createElement('div');
    panel.className = 'voice-confirm';
    panel.id = 'voice-confirm';
    panel.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button || !panel.contains(button)
          || !['voice-confirm-yes', 'voice-confirm-edit'].includes(button.id)) return;
      const transcript = panel.dataset.transcript;
      if (transcript === undefined) return;
      input.value = transcript;
      removeConfirmation();
      focusInput();
      say(button.id === 'voice-confirm-yes'
        ? 'Metin kutuda. Göndermek için Gönder\'e basın.'
        : 'Metni düzenleyebilirsiniz.');
    });
    return panel;
  }

  function showConfirmation(transcript) {
    if (!transcript) return;
    removeConfirmation();
    confirmation = createConfirmation();
    const text = document.createElement('p');
    text.id = 'voice-confirm-text';
    text.innerHTML = esc(confirmPrompt(transcript));
    const accept = document.createElement('button');
    accept.type = 'button';
    accept.className = 'btn';
    accept.id = 'voice-confirm-yes';
    accept.textContent = 'Doğru';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'btn';
    edit.id = 'voice-confirm-edit';
    edit.textContent = 'Düzelt';
    confirmation.dataset.transcript = transcript;
    confirmation.append(text);
    region.insertBefore(confirmation, status);
    const proceed = document.dispatchEvent(new CustomEvent('nabiz:voice-transcript', {
      cancelable: true, detail: { transcript, panel: confirmation },
    }));
    if (!proceed) return;
    confirmation.append(accept, edit);
    say('Anlaşılan metni onaylayın.');
  }

  function cancelSpeech() {
    utterance = null;
    if (synth) window.speechSynthesis.cancel();
    if (stopButton) stopButton.hidden = true;
  }

  function stopReading() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    cancelSpeech();
  }

  function stopRecognition(abort = true) {
    if (!recognition) return;
    const active = recognition;
    recognition = null;
    if (abort) {
      try {
        active.abort();
      } catch {
        // A recognition session can finish between the visibility event and abort().
      }
      say('Dinleme durduruldu.');
    }
    active.onresult = null;
    active.onerror = null;
    active.onend = null;
    resetTalkButton();
    if (preview) preview.textContent = '';
  }

  function speakAnswer(text) {
    if (!readingEnabled || !selectedVoice || !text.trim()) return;
    cancelSpeech();
    const next = new window.SpeechSynthesisUtterance(text.trim());
    next.lang = 'tr-TR';
    next.voice = selectedVoice;
    utterance = next;
    stopButton.hidden = false;
    next.onend = () => {
      if (utterance !== next) return;
      utterance = null;
      stopButton.hidden = true;
    };
    next.onerror = () => {
      if (utterance !== next) return;
      utterance = null;
      stopButton.hidden = true;
      say('Cevap sesli okunamadı.');
    };
    window.speechSynthesis.speak(next);
  }

  function readFinalMessage(message) {
    const item = message.target;
    if (!item.matches('li.chat-msg.is-assistant')) return;
    if (item.getAttribute('aria-busy') !== 'false' || item.classList.contains('is-error')) return;
    const final = item.querySelector('.chat-final');
    const text = item.querySelector('.chat-text');
    if (!final || !final.textContent.trim() || !text || readMessages.has(item)) return;
    readMessages.add(item);
    speakAnswer(text.textContent);
  }

  function refreshVoices() {
    selectedVoice = pickVoice(window.speechSynthesis.getVoices());
    if (!readButton) return;
    readButton.disabled = !selectedVoice;
    if (!selectedVoice) {
      readingEnabled = false;
      readButton.setAttribute('aria-pressed', 'false');
      stopReading();
      say(noVoiceMessage);
    } else if (status.textContent === noVoiceMessage) {
      say('');
    }
  }

  function startReading() {
    if (!log || !selectedVoice || !readButton) return;
    readingEnabled = true;
    readButton.setAttribute('aria-pressed', 'true');
    observer = new MutationObserver((messages) => {
      for (const message of messages) readFinalMessage(message);
    });
    observer.observe(log, { attributes: true, attributeFilter: ['aria-busy'], subtree: true });
  }

  function enableVoice() {
    optIn.setAttribute('aria-pressed', 'true');
    optIn.textContent = 'Sesle sorma açık';

    if (Recognition) {
      talkButton = document.createElement('button');
      talkButton.type = 'button';
      talkButton.className = 'btn';
      talkButton.id = 'voice-talk';
      talkButton.setAttribute('aria-pressed', 'false');
      talkButton.textContent = 'Bas, konuş';
      submit.before(talkButton);
      talkButton.addEventListener('click', () => {
        if (recognition) {
          try {
            recognition.stop();
          } catch {
            stopRecognition();
          }
          return;
        }
        let active;
        try {
          active = new Recognition();
        } catch {
          say(recognitionMessage('unknown'));
          return;
        }
        recognition = active;
        active.lang = 'tr-TR';
        active.interimResults = true;
        active.continuous = false;
        active.maxAlternatives = 1;
        let finalReceived = false;
        talkButton.setAttribute('aria-pressed', 'true');
        talkButton.textContent = 'Dinliyor, bitirmek için basın';
        say('Dinliyorum.');
        active.onresult = (event) => {
          let interim = '';
          let finalTranscript = '';
          for (let index = 0; index < event.results.length; index += 1) {
            const result = event.results[index];
            const text = (result[0] && result[0].transcript) || '';
            if (result.isFinal) finalTranscript += text;
            else if (index >= event.resultIndex) interim += text;
          }
          if (interim.trim()) preview.textContent = interim.trim();
          if (finalTranscript.trim()) {
            finalReceived = true;
            preview.textContent = '';
            showConfirmation(finalTranscript.trim());
          }
        };
        active.onerror = (event) => {
          say(recognitionMessage(event.error));
          removeConfirmation();
          preview.textContent = '';
        };
        active.onend = () => {
          if (recognition === active) recognition = null;
          resetTalkButton();
          if (!finalReceived && status.textContent === 'Dinliyorum.') say('Dinleme tamamlandı.');
          active.onresult = null;
          active.onerror = null;
          active.onend = null;
        };
        try {
          active.start();
        } catch {
          stopRecognition(false);
          say(recognitionMessage('not-allowed'));
        }
      });
    }

    preview = document.createElement('p');
    preview.className = 'voice-preview';
    preview.id = 'voice-preview';
    preview.setAttribute('aria-live', 'polite');

    confirmation = document.createElement('div');
    confirmation.className = 'voice-confirm';
    confirmation.id = 'voice-confirm';
    confirmation.hidden = true;

    region.insertBefore(preview, status);
    region.insertBefore(confirmation, status);

    if (synth) {
      readButton = document.createElement('button');
      readButton.type = 'button';
      readButton.className = 'btn';
      readButton.id = 'voice-read';
      readButton.setAttribute('aria-pressed', 'false');
      readButton.textContent = 'Cevabı sesli oku';
      stopButton = document.createElement('button');
      stopButton.type = 'button';
      stopButton.className = 'btn';
      stopButton.id = 'voice-stop';
      stopButton.hidden = true;
      stopButton.textContent = 'Okumayı durdur';
      region.insertBefore(readButton, status);
      region.insertBefore(stopButton, status);
      readButton.addEventListener('click', () => {
        if (readButton.disabled) return;
        if (readingEnabled) {
          readingEnabled = false;
          readButton.setAttribute('aria-pressed', 'false');
          stopReading();
        } else {
          startReading();
        }
      });
      stopButton.addEventListener('click', () => {
        cancelSpeech();
        say('Okuma durduruldu.');
      });
      voicesChanged = refreshVoices;
      window.speechSynthesis.addEventListener('voiceschanged', voicesChanged);
      refreshVoices();
    }
  }

  function disableVoice() {
    stopRecognition();
    readingEnabled = false;
    stopReading();
    if (voicesChanged) {
      window.speechSynthesis.removeEventListener('voiceschanged', voicesChanged);
      voicesChanged = null;
    }
    if (talkButton) talkButton.remove();
    if (preview) preview.remove();
    if (confirmation) confirmation.remove();
    if (readButton) readButton.remove();
    if (stopButton) stopButton.remove();
    talkButton = null;
    preview = null;
    confirmation = null;
    readButton = null;
    stopButton = null;
    selectedVoice = null;
    optIn.setAttribute('aria-pressed', 'false');
    optIn.textContent = 'Sesle sormayı aç';
    say('');
  }

  optIn.addEventListener('click', () => {
    if (optIn.getAttribute('aria-pressed') === 'true') disableVoice();
    else enableVoice();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && recognition) stopRecognition();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && recognition) stopRecognition();
  });
  form.addEventListener('submit', cancelSpeech);
}

export { DISCLOSURE, pickVoice, recognitionMessage, confirmPrompt, mountVoice };

if (typeof document !== 'undefined') mountVoice();
