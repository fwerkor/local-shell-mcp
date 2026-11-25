import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import ModelProviders from './ModelProviders';

jest.mock('librechat-data-provider', () => ({
  apiBaseUrl: () => '',
  QueryKeys: { models: 'models', endpoints: 'endpoints', tokenConfig: 'tokenConfig' },
  request: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));
jest.mock('~/components/Endpoints/SamplingFields', () => ({
  __esModule: true,
  default: () => null,
  samplingDraft: () => ({}),
  parseSampling: () => ({}),
}));

const get = jest.mocked(request.get);
const post = jest.mocked(request.post);
const put = jest.mocked(request.put);
const path = '/api/lsm/providers';
const catalog = { models: ['flash', 'pro'], model_contexts: { flash: 1048576 } };
const toggle = () => screen.getByRole('switch', { name: 'Automatically discover model information' });
const existing = {
  name: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com',
  models: ['old', 'flash'], model_contexts: { flash: 65536 },
  model_context_overrides: { flash: 65536 }, discovered_model_contexts: { flash: 1048576 },
  auto_discover: true, configured: true, source: 'named',
};

function mount() {
  return render(<QueryClientProvider client={new QueryClient()}><ModelProviders /></QueryClientProvider>);
}

async function addChannel() {
  mount();
  await screen.findByText(/No channels added yet/);
  fireEvent.click(screen.getByRole('button', { name: 'Add channel' }));
  fireEvent.change(screen.getByLabelText('Channel name'), { target: { value: 'DeepSeek' } });
  fireEvent.change(screen.getByLabelText('Model API base URL'), { target: { value: 'https://api.deepseek.com' } });
  fireEvent.change(screen.getByLabelText('Model API key'), { target: { value: 'key' } });
}

beforeEach(() => {
  get.mockResolvedValue({ providers: [] });
  put.mockResolvedValue({});
  post.mockResolvedValue(catalog);
});

it('defaults to automatic mode and previews metadata; saves only explicit context overrides', async () => {
  await addChannel();
  expect(toggle()).toBeChecked();
  expect(screen.queryByLabelText('Model identifiers')).not.toBeInTheDocument();
  await screen.findByText('Discovered 2 models');
  expect(post).toHaveBeenCalledWith(path + '/discover', {
    provider: 'openai', base_url: 'https://api.deepseek.com', api_key: 'key',
  });
  expect(screen.getByLabelText('Context window for flash')).toHaveAttribute('placeholder', '1048576');
  fireEvent.change(screen.getByLabelText('Context window for pro'), { target: { value: '8192' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    auto_discover: true, models: ['flash', 'pro'], model_contexts: { pro: 8192 },
  }));
});

it('saves automatic mode before preview finishes using the authoritative server discovery', async () => {
  await addChannel();
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    auto_discover: true, models: [], model_contexts: {},
  }));
});

it('does not turn off the toggle on preview failure; manual fallback is explicit', async () => {
  post.mockRejectedValueOnce(new Error('List unavailable'));
  await addChannel();
  await screen.findByText(/List unavailable/);
  expect(toggle()).toBeChecked();
  expect(put).not.toHaveBeenCalled();
  fireEvent.click(toggle());
  expect(toggle()).not.toBeChecked();
  fireEvent.change(screen.getByLabelText('Model identifiers'), { target: { value: 'manual' } });
  fireEvent.change(screen.getByLabelText('Context window for manual'), { target: { value: '8192' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(post).toHaveBeenCalledTimes(1);
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    auto_discover: false, models: ['manual'], model_contexts: { manual: 8192 },
  }));
});

it('replaces removed models and preserves explicit overrides in auto mode', async () => {
  get.mockResolvedValue({ providers: [existing] });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit DeepSeek' }));
  await screen.findByText('Discovered 2 models');
  expect(screen.queryByLabelText('Context window for old')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Context window for flash')).toHaveValue(65536);
  expect(post).toHaveBeenCalledWith(path + '/discover', {
    provider: 'openai', base_url: 'https://api.deepseek.com', existing_channel: 'DeepSeek',
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await waitFor(() => expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    auto_discover: true, models: ['flash', 'pro'], model_contexts: { flash: 65536 },
  })));
});

it('freezes current effective metadata when disabling auto mode', async () => {
  get.mockResolvedValue({ providers: [existing] });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit DeepSeek' }));
  await screen.findByText('Discovered 2 models');
  fireEvent.click(toggle());
  expect(screen.getByLabelText('Model identifiers')).toHaveValue('flash\npro');
  expect(screen.getByLabelText('Context window for flash')).toHaveValue(65536);
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    auto_discover: false, models: ['flash', 'pro'], model_contexts: { flash: 65536 },
  }));
});

it('ignores late discovery replies after switching to manual mode', async () => {
  let resolve: (value: typeof catalog) => void = () => {};
  post.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  await addChannel();
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
  fireEvent.click(toggle());
  fireEvent.change(screen.getByLabelText('Model identifiers'), { target: { value: 'manual' } });
  await act(async () => { resolve(catalog); });
  expect(screen.getByLabelText('Model identifiers')).toHaveValue('manual');
});

it('refreshes saved automatic channels immediately without editing', async () => {
  get.mockResolvedValue({ providers: [existing] });
  post.mockResolvedValueOnce({ providers: [existing] });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Refresh DeepSeek' }));
  await screen.findByText('Model information refreshed.');
  expect(post).toHaveBeenCalledWith(path + '/refresh', { channel: 'DeepSeek' });
  expect(put).not.toHaveBeenCalled();
});


it('uses the existing channel form for the fourth, Responses protocol', async () => {
  await addChannel();
  const protocol = screen.getByLabelText('Model provider');
  fireEvent.change(protocol, { target: { value: 'openai-responses' } });
  expect(screen.getByLabelText('Model API base URL')).toHaveValue('https://api.openai.com/v1');
  expect(toggle()).toBeChecked();
  await screen.findByText('Discovered 2 models');
  expect(post).toHaveBeenCalledWith(path + '/discover', {
    provider: 'openai-responses', base_url: 'https://api.openai.com/v1', api_key: 'key',
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({
    provider: 'openai-responses', auto_discover: true,
  }));
});
