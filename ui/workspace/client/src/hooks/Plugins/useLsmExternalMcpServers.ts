import { useQuery } from '@tanstack/react-query';
import { request } from 'librechat-data-provider';

export type MCPServer = {
  name: string;
  enabled: boolean;
  transport: string;
  tool_count: number;
};

type MCPServersResponse = { servers: MCPServer[] };

export const externalMcpServersQueryKey = ['lsm', 'external-mcp-servers'];

export function useLsmExternalMcpServers() {
  return useQuery<MCPServersResponse>({
    queryKey: externalMcpServersQueryKey,
    queryFn: () => request.get('/api/lsm/mcp/servers'),
    retry: false,
    staleTime: 30_000,
  });
}
