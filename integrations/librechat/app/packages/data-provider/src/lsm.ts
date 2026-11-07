import request from './request';

export const endpoint = '/api/lsm/controller';
export type RecordValue = Record<string, unknown>;
export type MachineRow = { machine?: string; name?: string; status?: string; online?: boolean; id?: string };
export type Entry = { name: string; type?: string; is_dir?: boolean; size?: number; path?: string };
type Envelope<T> = { ok: boolean; data: T; message?: string; error?: string };

export function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(name, String(value));
  }
  const result = search.toString();
  return result ? '?' + result : '';
}
export async function read<T>(route: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const result = await request.get<Envelope<T>>(endpoint + '/' + route + qs(params));
  if (!result.ok) throw new Error(result.message || result.error || 'Controller request failed');
  return result.data;
}
export async function write<T>(route: string, body: RecordValue): Promise<T> {
  const result = (await request.post(endpoint + '/' + route, body)) as Envelope<T>;
  if (!result.ok) throw new Error(result.message || result.error || 'Controller action failed');
  return result.data;
}
export async function binaryRequest(
  route: string, token: string | undefined, options: RequestInit = {},
): Promise<Response> {
  const response = await fetch(endpoint + '/' + route, {
    ...options,
    headers: {
      ...options.headers,
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
    },
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error('LSM request failed (' + response.status + ')');
  return response;
}
export const asText = (value: unknown): string => {
  if (value == null) return '—';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
};
export const formatBytes = (raw: unknown): string => {
  const size = Number(raw);
  if (!Number.isFinite(size) || size < 0) return '—';
  if (size < 1024) return size + ' B';
  const unit = Math.min(4, Math.floor(Math.log(size) / Math.log(1024)));
  return (size / (1024 ** unit)).toFixed(1) + ' ' + ['B', 'KiB', 'MiB', 'GiB', 'TiB'][unit];
};
