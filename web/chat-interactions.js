export function shouldSubmitOnEnter(event) {
  return event.key === "Enter"
    && !event.shiftKey
    && !event.isComposing
    && event.keyCode !== 229;
}

export function isNearBottom(metrics, threshold = 96) {
  const remaining = metrics.scrollHeight - metrics.clientHeight - metrics.scrollTop;
  return remaining <= threshold;
}

export function isAtBottom(metrics, tolerance = 2) {
  const remaining = metrics.scrollHeight - metrics.clientHeight - metrics.scrollTop;
  return remaining <= tolerance;
}

export function createRenderBatch() {
  return { anchor: null, contentChanged: false, programmatic: false };
}

export function queueRenderBatch(batch, { scrollTop, contentChanged, programmatic = false }) {
  return {
    anchor: batch.anchor === null ? scrollTop : batch.anchor,
    contentChanged: batch.contentChanged || Boolean(contentChanged),
    programmatic: batch.anchor === null ? Boolean(programmatic) : batch.programmatic,
  };
}

export function resetRenderBatch() {
  return createRenderBatch();
}

export function takeRenderBatch(batch) {
  return {
    anchor: batch.anchor,
    contentChanged: batch.contentChanged,
    programmatic: batch.programmatic,
    remaining: createRenderBatch(),
  };
}

export function initialScrollIntent() {
  return {
    followLatest: true,
    nearBottom: true,
    programmatic: false,
    userScrolling: false,
  };
}

export function reduceScrollIntent(state, action) {
  if (action.type === "reset") return initialScrollIntent();
  if (action.type === "programmatic-start") {
    return {
      ...state,
      followLatest: true,
      programmatic: true,
      userScrolling: false,
    };
  }

  const nearBottom = Boolean(action.nearBottom);
  const atBottom = Boolean(action.atBottom);
  if (action.type === "user-start") {
    return {
      followLatest: false,
      nearBottom,
      programmatic: false,
      userScrolling: true,
    };
  }
  if (action.type === "user-end") {
    return {
      followLatest: nearBottom,
      nearBottom,
      programmatic: false,
      userScrolling: false,
    };
  }
  if (action.type === "scroll") {
    if (state.programmatic) {
      return atBottom
        ? initialScrollIntent()
        : {
            followLatest: true,
            nearBottom,
            programmatic: true,
            userScrolling: false,
          };
    }
    if (state.userScrolling) {
      return {
        followLatest: false,
        nearBottom,
        programmatic: false,
        userScrolling: true,
      };
    }
    return {
      followLatest: state.followLatest,
      nearBottom,
      programmatic: false,
      userScrolling: false,
    };
  }
  return state;
}

export function shouldFollowNewContent(state, contentChanged) {
  return Boolean(contentChanged && state.followLatest && !state.userScrolling);
}

export function shouldRestoreRenderAnchor(state, anchor, contentChanged = false, programmaticOrigin = false) {
  return anchor !== null
    && anchor !== undefined
    && !state.programmatic
    && !state.userScrolling
    && (contentChanged || !programmaticOrigin);
}

export function isExplicitScrollIntent(event) {
  if (["wheel", "touchstart", "pointerdown"].includes(event.type)) return true;
  if (event.type !== "keydown" || event.defaultPrevented) return false;

  const tagName = String(event.target?.tagName || "").toUpperCase();
  if (event.target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tagName)) {
    return false;
  }
  return ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Spacebar"]
    .includes(event.key);
}

export function createFrameScheduler({ requestFrame, cancelFrame }) {
  let frameId = null;

  function cancel() {
    if (frameId === null) return;
    cancelFrame(frameId);
    frameId = null;
  }

  return {
    cancel,
    schedule(callback) {
      cancel();
      const scheduledId = requestFrame(() => {
        if (frameId !== scheduledId) return;
        frameId = null;
        callback();
      });
      frameId = scheduledId;
      return scheduledId;
    },
  };
}
