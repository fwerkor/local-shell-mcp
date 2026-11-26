/** @jest-environment-options {"url":"https://lsm.invalid/"} */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';
import ModelProviders, { isLoopback } from './ModelProviders';

let mockLocale: 'en' | 'zh-Hans' = 'en';

jest.mock('~/hooks/useLocalize', () => ({
  __esModule: true,
  default: () => (key: string, options: Record<string, unknown> = {}) => {
    const messages = mockLocale === 'zh-Hans'
      ? jest.requireActual('~/locales/zh-Hans/translation.json')
      : jest.requireActual('~/locales/en/translation.json');
    return (messages[key] ?? key).replace(/\{\{([^}]+)\}\}/g, (_: string, name: string) =>
      String(options[name] ?? ''));
  },
}));

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
  fireEvent.click(screen.getByRole('menuitem', { name: 'Manual configuration' }));
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

it('recognizes loopback hosts without relying on the API address', () => {
  for (const host of ['localhost', '127.0.0.1', '127.1.2.3', '[::1]', '::1']) {
    expect(isLoopback(host)).toBe(true);
  }
  for (const host of ['192.168.1.1', 'localhost.example.org', '127.0.0.1.example.org', 'lsm.invalid']) {
    expect(isLoopback(host)).toBe(false);
  }
});

it('shows the remote callback instructions before opening the official authorization page', async () => {
  const popup = jest.spyOn(window, 'open').mockReturnValue(null);
  try {
    post.mockResolvedValueOnce({ flow: 'mock-flow', authorization_url: 'https://auth.openai.com/example', manual: true });
    get.mockImplementation(async (target) => target.includes('/oauth/status') ?
      { status: 'pending' } : { providers: [] });
    mount();
    await screen.findByText(/No channels added yet/);
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Continue with ChatGPT' }));
    expect(screen.getByRole('dialog', { name: 'Connect account' })).toBeInTheDocument();
    expect(popup).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Start authorization' }));
    const field = await screen.findByLabelText('Full callback URL');
    expect(popup).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith(path + '/oauth/start', {
      method: 'chatgpt', name: 'Codex', reauthorize: false, manual: true,
    });
    expect(screen.getByRole('button', { name: 'Complete authorization' })).toBeDisabled();
    fireEvent.change(field, { target: { value: 'http://127.0.0.1:1455/auth/callback?code=mock' } });
    fireEvent.click(screen.getByRole('button', { name: 'Complete authorization' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(path + '/oauth/status?flow=mock-flow', {
      callback_url: 'http://127.0.0.1:1455/auth/callback?code=mock',
    }));
    expect(await screen.findByRole('button', { name: 'Completing authorization…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  } finally {
    popup.mockRestore();
  }
});

it('allows pasting the same callback when the local listener is unreachable', async () => {
  const popup = jest.spyOn(window, 'open').mockReturnValue(null);
  try {
    post.mockResolvedValueOnce({ flow: 'container-flow', authorization_url: 'https://auth.openai.com/example', manual: false });
    get.mockImplementation(async (target) => target.includes('/oauth/status') ?
      { status: 'pending' } : { providers: [] });
    mount();
    await screen.findByText(/No channels added yet/);
    fireEvent.click(screen.getByRole('button', { name: 'Add channel' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Continue with ChatGPT' }));
    const start = screen.queryByRole('button', { name: 'Start authorization' });
    if (start) fireEvent.click(start);
    fireEvent.click(await screen.findByText('Callback not received?'));
    const field = await screen.findByLabelText('Full callback URL');
    fireEvent.change(field, { target: { value: 'http://127.0.0.1:1455/auth/callback?code=mock&state=mock' } });
    fireEvent.click(screen.getByRole('button', { name: 'Complete authorization' }));
    await waitFor(() => expect(post).toHaveBeenCalledWith(path + '/oauth/status?flow=container-flow', {
      callback_url: 'http://127.0.0.1:1455/auth/callback?code=mock&state=mock',
    }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  } finally {
    popup.mockRestore();
  }
});

it('localizes the manual account authorization instructions and callback controls', async () => {
  mockLocale = 'zh-Hans';
  const popup = jest.spyOn(window, 'open').mockReturnValue(null);
  try {
    post.mockResolvedValueOnce({ flow: 'localized-flow', authorization_url: 'https://auth.openai.com/example', manual: true });
    get.mockImplementation(async (target) => target.includes('/oauth/status') ?
      { status: 'pending' } : { providers: [] });
    mount();
    const messages = jest.requireActual('~/locales/zh-Hans/translation.json');
    fireEvent.click(await screen.findByRole('button', { name: messages.com_lsm_channel_add }));
    fireEvent.click(screen.getByRole('menuitem', { name: '使用 ChatGPT 账号继续' }));
    expect(screen.getByRole('dialog', { name: '连接账号' })).toBeInTheDocument();
    expect(screen.getByText('当前通过非回环地址访问 LSM 实例，需要手动完成 OAuth 回调。')).toBeInTheDocument();
    expect(screen.getByText(/出现连接错误属于正常现象/)).toBeInTheDocument();
    expect(screen.getByText(/请勿在其他地方分享此链接/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '开始授权' }));
    expect(await screen.findByLabelText('完整回调 URL')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '完成授权' })).toBeDisabled();
    expect(screen.getByRole('link', { name: '重新打开授权页面' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: messages.com_ui_cancel }));
  } finally {
    popup.mockRestore();
    mockLocale = 'en';
  }
});
