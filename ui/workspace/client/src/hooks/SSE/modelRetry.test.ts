import { modelRetryNotice } from './modelRetry';

describe('modelRetryNotice', () => {
  it('formats a retry without exposing upstream error contents', () => {
    expect(
      modelRetryNotice(
        {
          attempt: 3,
          maximum: 8,
          delaySeconds: 4,
          httpStatus: 504,
          detail: 'private upstream data',
        },
        '重试',
      ),
    ).toBe('HTTP 504 · 重试 3/8 · 4s');
  });

  it('formats transport failures without an HTTP status', () => {
    expect(
      modelRetryNotice(
        {
          attempt: 1,
          maximum: 8,
          delaySeconds: 1.2,
          httpStatus: null,
        },
        'Retry',
      ),
    ).toBe('Retry 1/8 · 2s');
  });

  it.each([null, {}, { attempt: 9, maximum: 8, delaySeconds: 1 }])(
    'rejects invalid retry events: %p',
    (data) => expect(modelRetryNotice(data, 'Retry')).toBeUndefined(),
  );
});
