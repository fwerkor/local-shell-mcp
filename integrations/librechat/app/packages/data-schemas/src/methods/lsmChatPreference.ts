import type { Connection, Model } from 'mongoose';

export type LsmChatPreference = { web: boolean; lsm: boolean; mcp: boolean; memory: boolean };

/** MongoDB operations are confined to the data-schemas workspace. */
export function createLsmChatPreferenceStore(connection: unknown, conversationModel: () => unknown) {
  const collection = (connection as Connection).collection('lsm_chat_preferences');
  return {
    async isOwner(userId: string, conversationId: string): Promise<boolean> {
      const Conversation = conversationModel() as Model<unknown>;
      return !!(await Conversation.exists({ user: userId, conversationId }));
    },
    async read(userId: string, conversationId: string): Promise<Partial<LsmChatPreference> | null> {
      const stored = await collection.findOne({ userId, conversationId });
      if (!stored) return null;
      return {
        web: stored.web as boolean, lsm: stored.lsm as boolean,
        mcp: stored.mcp as boolean, memory: stored.memory as boolean,
      };
    },
    async save(userId: string, conversationId: string, prefs: LsmChatPreference): Promise<number> {
      await collection.createIndex({ userId: 1, conversationId: 1 }, { unique: true });
      const result = await collection.findOneAndUpdate(
        { userId, conversationId },
        {
          $set: prefs,
          $inc: { revision: 1 },
          $setOnInsert: { userId, conversationId },
        },
        { upsert: true, returnDocument: 'after' },
      );
      const revision = Number(result?.revision);
      if (!Number.isSafeInteger(revision) || revision < 1) {
        throw new Error('MongoDB failed to issue a chat policy revision');
      }
      return revision;
    },
  };
}
