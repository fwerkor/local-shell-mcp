import type { Connection, Model } from 'mongoose';

export function createLsmAuthStore(connection: unknown, userModel: () => unknown) {
  const nonces = (connection as Connection).collection<{ _id: string; expiresAt: Date }>('lsm_login_nonces');
  return {
    async claimTicket(jti: string, expiresAt: Date): Promise<void> {
      await nonces.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 });
      await nonces.insertOne({ _id: jti, expiresAt });
    },
    async getWorkspaceUser(): Promise<string> {
      const email = 'workspace@local-shell-mcp.invalid';
      const User = userModel() as Model<unknown>;
      const user = await User.findOneAndUpdate(
        { email, provider: 'lsm' },
        { $setOnInsert: {
          username: 'lsm_workspace',
          name: 'Local Shell MCP',
          email,
          provider: 'lsm',
          emailVerified: true,
          role: 'USER',
        } },
        { upsert: true, new: true, runValidators: true },
      );
      if (!user) throw new Error('Unable to provision LSM workspace user');
      return String(user._id);
    },
  };
}
