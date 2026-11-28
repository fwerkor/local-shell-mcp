import { useEffect, useRef, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { useStore } from 'jotai';
import { buildThreadIndex, messageBranchSelections, ROOT_KEY } from '~/utils/thread';
import { siblingIdxFamily, siblingKey } from './Thread/state';
import { useAtomValue } from 'jotai';
import { useRecoilValue } from 'recoil';
import { Constants } from 'librechat-data-provider';
import type { TMessage } from 'librechat-data-provider';
import { useScreenshot, useMessageScrolling, useScrollbarGutter, useLocalize } from '~/hooks';
import { MessagesViewProvider, useChatContext, useFileMapContext } from '~/Providers';
import { RowMountProvider, useProgressiveRowMount } from '~/hooks/Messages';
import { useChatSurface } from '~/components/Chat/Subagents/surface';
import useThreadRows from '~/hooks/Messages/useThreadRows';
import { steerOverlayHeightFamily } from '~/store/steer';
import { autoScrollAtom } from '~/store/autoScroll';
import { FLAT_THREAD, ThreadList } from './Thread';
import { fontSizeAtom } from '~/store/fontSize';
import MultiMessage from './MultiMessage';
import ScrollButton from './ScrollButton';
import PendingTurn from './PendingTurn';
import MessageNav from './MessageNav';
import { cn } from '~/utils';
import store from '~/store';

function MessagesViewContent({
  messagesTree: _messagesTree,
  messages,
  isFetching = false,
}: {
  messagesTree?: TMessage[] | null;
  messages?: TMessage[] | null;
  isFetching?: boolean;
}) {
  const localize = useLocalize();
  const location = useLocation();
  const route = useParams();
  const target = new URLSearchParams(location.search).get('message');
  const fontSize = useAtomValue(fontSizeAtom);
  const { screenshotTargetRef } = useScreenshot();
  const [currentEditId, setCurrentEditId] = useState<number | string | null>(-1);

  const {
    conversation,
    contentRef,
    scrollableRef,
    messagesEndRef,
    handleSmoothToRef,
    debouncedHandleScroll,
    handleNearBottomChange,
  } = useMessageScrolling(_messagesTree, !!target);

  useScrollbarGutter(scrollableRef);

  const { conversationId } = conversation ?? {};
  const fileMap = useFileMapContext();
  const threadRows = useThreadRows(FLAT_THREAD ? messages : null, conversationId, fileMap);

  const { index, latestMessageDepth } = useChatContext();
  const isSubmitting = useRecoilValue(store.isSubmittingFamily(index));
  const { showScrollButton, maximizeChatSpace } = useChatSurface();
  const autoScroll = useAtomValue(autoScrollAtom);
  /** Re-arm from the conversation that owns the RENDERED tree: the Recoil
   *  conversation id lags the route during warm-cache navigation, and keying
   *  off it would first mount the new tree unwindowed, then narrow it after
   *  the fact — visibly unmounting rows the user is already reading. */
  const treeConversationId = _messagesTree?.[0]?.conversationId ?? conversationId;
  const mountWindow = useProgressiveRowMount({
    tailDepth: FLAT_THREAD ? undefined : latestMessageDepth,
    anchorBottom: !target && (autoScroll || isSubmitting),
    isSubmitting,
    conversationId: treeConversationId,
    scrollableRef,
  });

  const jotai = useStore();
  const completedJump = useRef<string | null>(null);
  const jumpKey = target ? location.key + ':' + target : null;

  useEffect(() => {
    if (
      !target ||
      !jumpKey ||
      completedJump.current === jumpKey ||
      !messages ||
      route.conversationId !== treeConversationId ||
      !messages.some((message) => message.messageId === target)
    )
      return;
    const thread = buildThreadIndex(messages);
    for (const [key, position] of messageBranchSelections(thread, target)) {
      jotai.set(
        siblingIdxFamily(key === ROOT_KEY ? siblingKey(treeConversationId) : key),
        position,
      );
    }
    let frame = 0;
    let attempts = 0;
    let positionedPlaceholder = false;
    const reveal = () => {
      const element = document.getElementById(target);
      const container = scrollableRef.current;
      if (element && container?.contains(element)) {
        const placeholder = element.closest('[data-history-body="placeholder"]');
        if (!placeholder || !positionedPlaceholder) {
          container.scrollTop +=
            element.getBoundingClientRect().top - container.getBoundingClientRect().top - 64;
          positionedPlaceholder = true;
        }
        // A virtual anchor is not the final message. Re-land after its body
        // and any preceding visible rows hydrate, rather than marking an
        // estimated position as a completed bookmark jump.
        if (!placeholder) {
          element.animate?.(
            [{ outline: '2px solid currentColor' }, { outline: '2px solid transparent' }],
            { duration: 1600 },
          );
          completedJump.current = jumpKey;
          return;
        }
      }
      if (++attempts < 180) {
        frame = requestAnimationFrame(reveal);
      }
    };
    frame = requestAnimationFrame(reveal);
    return () => cancelAnimationFrame(frame);
  }, [target, jumpKey, messages, treeConversationId, route.conversationId, jotai, scrollableRef]);

  /** The in-flight steer overlay floats above the composer over the bottom of
   *  the thread (see `InFlightSteers`); reserve an equal band here so the
   *  newest message rests above it and older ones scroll behind. */
  const overlayConversationId = conversationId ?? Constants.NEW_CONVO;
  const steerOverlayHeight = useAtomValue(steerOverlayHeightFamily(overlayConversationId));

  return (
    <>
      <div className="relative flex-1 overflow-hidden overflow-y-auto">
        <div className="relative h-full">
          <div
            className="scrollbar-gutter-stable"
            onScroll={debouncedHandleScroll}
            ref={scrollableRef}
            style={{
              height: '100%',
              overflowY: 'auto',
              width: '100%',
              /** The mount hook pins the anchor row itself (document-space
               *  measurement); native scroll anchoring reacting to the same
               *  insertions would double-correct. */
              overflowAnchor: mountWindow != null ? 'none' : undefined,
            }}
          >
            <div
              ref={contentRef}
              className="flex flex-col pb-9 pt-14"
              style={
                steerOverlayHeight > 0
                  ? { paddingBottom: `calc(2.25rem + ${steerOverlayHeight}px)` }
                  : undefined
              }
            >
              {(_messagesTree && _messagesTree.length == 0) || _messagesTree === null ? (
                <div
                  className={cn(
                    'flex w-full items-center justify-center p-3 text-text-secondary',
                    fontSize,
                  )}
                >
                  {localize('com_ui_nothing_found')}
                </div>
              ) : (
                <>
                  <div ref={screenshotTargetRef} data-testid="screenshot-target">
                    <RowMountProvider mountWindow={target ? null : mountWindow}>
                      {FLAT_THREAD && threadRows ? (
                        <ThreadList
                          rows={threadRows}
                          scrollableRef={scrollableRef}
                          conversationId={treeConversationId}
                          anchorBottom={!target && (autoScroll || isSubmitting)}
                          target={target}
                          isSubmitting={isSubmitting}
                          isFetching={isFetching}
                          setCurrentEditId={setCurrentEditId}
                          currentEditId={currentEditId ?? null}
                        />
                      ) : (
                        <MultiMessage
                          messagesTree={_messagesTree}
                          messageId={conversationId ?? null}
                          setCurrentEditId={setCurrentEditId}
                          currentEditId={currentEditId ?? null}
                        />
                      )}
                    </RowMountProvider>
                  </div>
                  <PendingTurn
                    scrollableRef={scrollableRef}
                    messages={messages}
                    maximizeChatSpace={maximizeChatSpace}
                  />
                </>
              )}
              <div
                id="messages-end"
                className="group h-0 w-full flex-shrink-0"
                ref={messagesEndRef}
              />
            </div>
          </div>

          <ScrollButton
            conversationId={overlayConversationId}
            enabled={showScrollButton}
            maximizeChatSpace={maximizeChatSpace}
            scrollableRef={scrollableRef}
            messagesEndRef={messagesEndRef}
            scrollHandler={handleSmoothToRef}
            onNearBottomChange={handleNearBottomChange}
            overlayHeight={steerOverlayHeight}
          />

          <MessageNav scrollableRef={scrollableRef} />
        </div>
      </div>
    </>
  );
}

export default function MessagesView({
  messagesTree,
  messages,
  isFetching = false,
}: {
  messagesTree?: TMessage[] | null;
  messages?: TMessage[] | null;
  isFetching?: boolean;
}) {
  return (
    <MessagesViewProvider>
      <MessagesViewContent
        messagesTree={messagesTree}
        messages={messages}
        isFetching={isFetching}
      />
    </MessagesViewProvider>
  );
}
