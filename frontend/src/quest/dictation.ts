/**
 * Saying a furniture description instead of typing it (#188), with the browser's own speech
 * recognition. Where a browser has none, or the microphone is refused, it says so plainly and
 * the description can still be typed.
 */

/** The part of the Web Speech API used here; TypeScript's DOM types don't include it. */
interface Transcript { transcript: string }
interface RecognitionResult extends ArrayLike<Transcript> { isFinal: boolean }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type RecognitionConstructor = new () => Recognition;

/** What dictation tells the page. */
export interface DictationEvents {
  /** The words heard so far, from the start of this hold. */
  heard: (text: string) => void;
  /** Why dictation can't run or stopped, as the page shows it. */
  failed: (message: string) => void;
  /** Recognition has stopped, whether it heard anything or not. */
  ended: () => void;
}

export const NO_RECOGNITION =
  'Speaking isn\'t available in this browser, so type the description instead.';
const REFUSED = 'The microphone was refused, so type the description instead, or allow the microphone and try again.';
const FAILED = 'Nothing was heard. Hold to speak again, or type the description.';
/** The server takes a description of at most this many characters. */
const LONGEST = 200;

/** The browser's speech recognition, if it has one. */
function recognitionClass(): RecognitionConstructor | null {
  const found = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor };
  return found.SpeechRecognition ?? found.webkitSpeechRecognition ?? null;
}

/** One hold of the talk button: listens from `start` until `stop`. */
export class Dictation {
  private recognition: Recognition | null = null;

  constructor(private readonly events: DictationEvents) {}

  get listening(): boolean {
    return this.recognition !== null;
  }

  /** Starts listening; false, with the reason given to `failed`, when it can't. */
  start(language = navigator.language || 'en-GB'): boolean {
    if (this.recognition) return true;
    const Recognition = recognitionClass();
    if (!Recognition) {
      this.events.failed(NO_RECOGNITION);
      return false;
    }
    const recognition = new Recognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.onresult = event => {
      // Every result of this hold, guesses included, joined in order.
      const words = Array.from(event.results, result => result[0]?.transcript ?? '').join(' ');
      this.events.heard(words.replace(/\s+/g, ' ').trim().slice(0, LONGEST));
    };
    recognition.onerror = event => {
      if (event.error === 'aborted') return;
      this.events.failed(event.error === 'not-allowed' || event.error === 'service-not-allowed' ? REFUSED : FAILED);
      // Some engines never send onend after an error: listening ends here either way.
      this.finish(recognition);
      recognition.stop();
    };
    recognition.onend = () => this.finish(recognition);
    this.recognition = recognition;
    try {
      recognition.start();
    } catch {
      this.recognition = null;
      this.events.failed(FAILED);
      return false;
    }
    return true;
  }

  /** Ends this recognition's listening once, however it ended. */
  private finish(recognition: Recognition): void {
    if (this.recognition !== recognition) return;
    this.recognition = null;
    this.events.ended();
  }

  /** Stops listening; what was heard stays. */
  stop(): void {
    this.recognition?.stop();
  }
}
