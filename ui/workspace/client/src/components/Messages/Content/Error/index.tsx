// file deepcode ignore HardcodedNonCryptoSecret: No hardcoded secrets
import { parseLangChainErrorCode } from 'librechat-data-provider';
import type { TranslationKeys } from '~/hooks';
import type { ErrorSource } from './source';
import type { ErrorPayload } from './parts';
import { errorCopy, errorRenderers } from './registry';
import { UnclassifiedError } from './ProviderError';
import { extractJson, isJson } from '~/utils/json';
import { ErrorBody, ErrorDetails, readObject, readString } from './parts';
import { useErrorSource } from './source';
import { useLocalize } from '~/hooks';

/**
 * The server converts classified LangChain failures into typed payloads, but messages persisted
 * before it did still carry the docs URL, so the code is read back out of the text to localize
 * those the same way. Codes without copy fall through to the provider text, stripped of the URL.
 */
const langChainErrorKeys: Record<string, TranslationKeys> = {
  MODEL_NOT_FOUND: 'com_error_model_not_found',
  MODEL_RATE_LIMIT: 'com_error_model_rate_limit',
};

function getLangChainErrorKey(text: string): TranslationKeys | undefined {
  const code = parseLangChainErrorCode(text);
  return code == null ? undefined : langChainErrorKeys[code];
}

/**
 * Renders a failed turn from whatever the server managed to persist.
 *
 * Three kinds of text arrive here: a typed payload this app produced, a provider's own error body,
 * and unclassified prose. A payload with copy wins, because it is the only one written for a
 * reader; everything else is shown through `UnclassifiedError`, which leads with what is known and
 * keeps the raw provider text as a detail rather than as the headline.
 *
 * `message` is the row when the caller has it; an error content part renders without one and reads
 * its row's identity from `ErrorSourceProvider` instead.
 */
const ErrorContent = ({ text, message: rowMessage }: { text: string; message?: ErrorSource }) => {
  const localize = useLocalize();
  const contextSource = useErrorSource();
  const message = rowMessage ?? contextSource;

  const langChainErrorKey = getLangChainErrorKey(text);
  if (langChainErrorKey != null) {
    return localize(langChainErrorKey);
  }

  const jsonString = extractJson(text);
  if (!isJson(jsonString)) {
    return <UnclassifiedError text={text} message={message} />;
  }

  const json = JSON.parse(jsonString) as ErrorPayload;
  if (readString(json, 'type') === 'lsm_generation_error') {
    return <>{readString(json, 'message') ?? 'LSM generation failed.'}</>;
  }
  /**
   * OpenAI-compatible bodies nest their `code` and `type` under `error`. When the top level names
   * neither, that envelope is the payload a renderer reads; a top-level `type`, even a generic one
   * like Anthropic's `"error"`, keeps the body as it is.
   */
  const envelope = readObject(json, 'error');
  const topLevelKey = readString(json, 'code') ?? readString(json, 'type');
  const nestedKey =
    topLevelKey == null
      ? (readString(envelope, 'code') ?? readString(envelope, 'type'))
      : undefined;
  const payload = nestedKey != null && envelope != null ? envelope : json;
  const errorKey = topLevelKey ?? nestedKey;

  if (errorKey != null) {
    const Renderer = errorRenderers[errorKey];
    if (Renderer != null) {
      return <Renderer json={payload} text={text} message={message} />;
    }
    const copyKey = errorCopy[errorKey];
    if (copyKey != null) {
      return localize(copyKey);
    }
  }

  return <UnclassifiedError json={json} text={text} message={message} />;
};

/** Every error retains a collapsed, copyable diagnostic body, including
 * runtime failures, provider failures and legacy plain-text error records. */
const Error = ({ text, message }: { text: string; message?: ErrorSource }) => {
  const localize = useLocalize();
  const jsonText = extractJson(text);
  let details = text;
  if (isJson(jsonText)) {
    try {
      const payload = JSON.parse(jsonText) as ErrorPayload;
      details = readString(payload, 'type') === 'lsm_generation_error'
        ? (readString(payload, 'details') ?? JSON.stringify(payload, null, 2))
        : JSON.stringify(payload, null, 2);
    } catch {
      // Legacy non-JSON failures still show their original message.
    }
  }
  return (
    <ErrorBody>
      <ErrorContent text={text} message={message} />
      <ErrorDetails label={localize('com_error_details_diagnostic')}>
        <pre className="whitespace-pre-wrap break-all font-mono select-text">
          {details}
        </pre>
      </ErrorDetails>
    </ErrorBody>
  );
};

export default Error;
