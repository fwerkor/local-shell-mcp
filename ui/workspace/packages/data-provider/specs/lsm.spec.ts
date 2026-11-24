import { binaryRequest, controllerError } from '../src/lsm';

describe('LSM controller errors', () => {
  it('shows the backend message instead of the generic Axios 400 error', () => {
    const error = {
      isAxiosError: true,
      message: 'Request failed with status code 400',
      response: { data: { ok: false, error: 'GuiUnavailableError', message: 'No graphical Linux session was found' } },
    };
    expect(controllerError(error).message).toBe('No graphical Linux session was found');
  });

  it('shows the server message for failed binary frame requests', async () => {
    const fetchMock = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ message: 'Window capture is unavailable' }),
    } as Response);
    try {
      await expect(binaryRequest('gui/frame?machine=local', undefined)).rejects.toThrow(
        'Window capture is unavailable',
      );
    } finally {
      fetchMock.mockRestore();
    }
  });

  it('preserves unrelated errors', () => {
    const error = new Error('Connection lost');
    expect(controllerError(error)).toBe(error);
  });
});
