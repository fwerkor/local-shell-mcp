import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

function mount() {
  render(<QueryClientProvider client={new QueryClient()}><ModelProviders /></QueryClientProvider>);
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

it('discovers the catalog on save with no model input and saves reported windows', async () => {
  await addChannel();
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(post).toHaveBeenCalledWith(path + '/discover', {
    provider: 'openai', base_url: 'https://api.deepseek.com', api_key: 'key',
  });
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining(catalog));
});

it('opens manual fallback when discovery fails and does not save an empty catalog', async () => {
  post.mockRejectedValueOnce(new Error('List unavailable'));
  await addChannel();
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('List unavailable');
  expect(screen.getByText('Edit models and context windows manually').closest('details')).toHaveAttribute('open');
  expect(put).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Model identifiers'), { target: { value: 'manual' } });
  fireEvent.change(screen.getByLabelText('Context window for manual'), { target: { value: '8192' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await screen.findByText('Channel saved.');
  expect(post).toHaveBeenCalledTimes(1);
  expect(put).toHaveBeenCalledWith(path, expect.objectContaining({ models: ['manual'], model_contexts: { manual: 8192 } }));
});

it('refreshes an existing channel without losing manual aliases or context overrides', async () => {
  get.mockResolvedValue({ providers: [{ name: 'DeepSeek', provider: 'openai', base_url: 'https://api.deepseek.com', models: ['alias', 'flash'], model_contexts: { flash: 65536 }, configured: true, source: 'named' }] });
  mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit DeepSeek' }));
  fireEvent.click(screen.getByRole('button', { name: 'Fetch models' }));
  await screen.findByText('Fetched 2 models. Save to apply.');
  expect(put).not.toHaveBeenCalled();
  expect(post).toHaveBeenCalledWith(path + '/discover', {
    provider: 'openai', base_url: 'https://api.deepseek.com', existing_channel: 'DeepSeek',
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save model channel' }));
  await waitFor(() => expect(put).toHaveBeenCalledWith(path, expect.objectContaining({ models: ['alias', 'flash', 'pro'], model_contexts: { flash: 65536 } })));
});
