(() => {
  let ws = null;
  let state = null;
  let originalState = null;
  let discordMetadata = null;
  let hasRetriedGuilds = false;
  let selectedPingIndex = 0;
  let backups = [];
  let hasPendingPingChanges = false;

  // Constants for magic strings
  const ACTION_GET_STATE = "get_state";
  const ACTION_SAVE_PARSED = "save_parsed";
  const ACTION_FIRE_DEAL = "fire_deal";
  const ACTION_SAVE_RAW = "save_raw";
  const ACTION_VALIDATE_RAW = "validate_raw";
  const ACTION_EXPORT_JSON = "export_json";
  const ACTION_SAVE_BLOCKLIST = "save_global_blocklist";
  const ACTION_GET_BACKUPS = "get_backups";
  const ACTION_RESTORE_BACKUP = "restore_backup";
  const ACTION_EXTEND_SESSION = "extend_session";
  const ACTION_CREATE_BACKUP = "create_manual_backup";

  const dealNames = ["fire_deal", "great_deal", "good_deal", "ok_deal"];

  const statusEl = document.getElementById("status");
  const pingListEl = document.getElementById("pingList");
  const pingFormEl = document.getElementById("pingForm");
  const keywordCardsEl = document.getElementById("keywordCards");
  const pingSaveDockEl = document.getElementById("pingSaveDock");
  const blocklistContainer = document.getElementById("blocklistContainer");
  
  // Blocklist diff tracking
  let originalBlocklist = [];
  let blocklistDiff = { added: [], removed: [] };
  
  // Global click listener to close any open custom selects
  document.addEventListener("click", () => {
    document.querySelectorAll(".select-menu.open").forEach(m => m.classList.remove("open"));
  });
  const backupListEl = document.getElementById("backupList");
  const backupMetaEl = document.getElementById("backupMeta");
  const btnSavePingEl = document.getElementById("btnSavePing");
  const btnSaveBlocklist = document.getElementById("btnSaveBlocklist");
  const btnDiscardBlocklist = document.getElementById("btnDiscardBlocklist");
  const btnAddBlocklist = document.getElementById("btnAddBlocklist");
  const confirmOverlayEl = document.getElementById("confirmOverlay");
  const confirmModalEl = document.getElementById("confirmModal");
  const confirmTitleEl = document.getElementById("confirmTitle");
  const confirmBodyEl = document.getElementById("confirmBody");
  const confirmOkBtnEl = document.getElementById("confirmOkBtn");
  const confirmCancelBtnEl = document.getElementById("confirmCancelBtn");
  const settingsContainer = document.getElementById("settingsContainer");
  const btnSaveSettings = document.getElementById("btnSaveSettings");
  const btnDiscardSettings = document.getElementById("btnDiscardSettings");
  const roleGroupsContainer = document.getElementById("roleGroupsContainer");
  const btnSaveRoles = document.getElementById("btnSaveRoles");
  const btnDiscardRoles = document.getElementById("btnDiscardRoles");
  const btnAddRoleGroup = document.getElementById("btnAddRoleGroup");
  const blocklistAddOverlayEl = document.getElementById("blocklistAddOverlay");
  const blocklistAddModeEl = document.getElementById("blocklistAddMode");
  const blocklistAddModeCustomEl = document.getElementById("blocklistAddModeCustom");
  const blocklistAddValueEl = document.getElementById("blocklistAddValue");
  const blocklistAddHintEl = document.getElementById("blocklistAddHint");
  const btnBlocklistAddCancelEl = document.getElementById("btnBlocklistAddCancel");
  const btnBlocklistAddApplyEl = document.getElementById("btnBlocklistAddApply");
  let blocklistAddModeDropdown = null;

  let confirmResolver = null;

  // Session management
  let sessionExpiryTime = null;
  let sessionCheckInterval = null;
  const SESSION_DURATION_MS = 30 * 60 * 1000;
  const SESSION_WARNING_THRESHOLD_MS = 5 * 60 * 1000;
  
  const SESSION_MESSAGES = {
    expiryWarning: (seconds) => `Your session will expire in ${seconds} second${seconds > 1 ? 's' : ''}.`,
    sessionExtended: 'Session extended by 30 minutes',
    sessionExpired: 'Session expired. Please log in again.',
    extendFailed: 'Failed to extend session. Please log in again.',
    extendError: 'Error extending session',
  };

  const sessionExpiryOverlayEl = document.getElementById("sessionExpiryOverlay");
  const sessionExpiryTitleEl = document.getElementById("sessionExpiryTitle");
  const sessionExpiryBodyEl = document.getElementById("sessionExpiryBody");
  const btnSessionExtend = document.getElementById("btnSessionExtend");
  const btnSessionLogout = document.getElementById("btnSessionLogout");

  function updateSessionExpiry() {
    sessionExpiryTime = Date.now() + SESSION_DURATION_MS;
    checkSessionExpiry();
  }

  function checkSessionExpiry() {
    if (!sessionExpiryTime) return;

    const timeLeft = sessionExpiryTime - Date.now();

    if (timeLeft <= 0) {
      // Session expired - auto logout without reload
      setStatus(SESSION_MESSAGES.sessionExpired, "error");
      
      // Clear all state and redirect to login
      ws.close();
      state = null;
      originalState = null;
      window.location.href = "/";
      return;
    }

    if (timeLeft <= SESSION_WARNING_THRESHOLD_MS) {
      // Show warning modal if not already showing
      if (!sessionExpiryOverlayEl.classList.contains("open")) {
        sessionExpiryOverlayEl.classList.add("open");
        sessionExpiryOverlayEl.setAttribute("aria-hidden", "false");
      }
      
      const secondsLeft = Math.ceil(timeLeft / 1000);
      sessionExpiryBodyEl.textContent = SESSION_MESSAGES.expiryWarning(secondsLeft);
    }

    sessionCheckInterval = setTimeout(checkSessionExpiry, 1000);
  }

  async function extendSession() {
    try {
      const response = await fetch("/extend_session", {
        method: "POST",
        credentials: "same-origin",
      });

      if (response.ok) {
        sessionExpiryOverlayEl.classList.remove("open");
        sessionExpiryOverlayEl.setAttribute("aria-hidden", "true");
        updateSessionExpiry();
        setStatus(SESSION_MESSAGES.sessionExtended, "ok");
      } else {
        setStatus(SESSION_MESSAGES.extendFailed, "error");
        window.location.href = "/";
      }
    } catch (err) {
      showError(SESSION_MESSAGES.extendError);
    }
  }

  function toTitleCase(str) {
    let string = str.split(" ").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
    string = string.replace("Ok", "OK");
    return string;
  }

  function ensureItemKeywordConfig(item) {
    if (!item || typeof item !== "object") return { mode: "poll", filter: "", query: null };
    let repaired = false;
    const repairReasons = [];
    if (!item.keyword || typeof item.keyword !== "object") {
      item.keyword = { mode: "poll", filter: "", query: null };
      repaired = true;
      repairReasons.push("missing keyword object");
    }
    const hasQueryText = typeof item.keyword.query === "string" && item.keyword.query.trim() !== "";
    const modeValue = String(item.keyword.mode || "").trim().toLowerCase();
    if (modeValue === "poll" || modeValue === "query") {
      item.keyword.mode = modeValue;
    } else if (!modeValue) {
      item.keyword.mode = hasQueryText ? "query" : "poll";
      repaired = true;
      repairReasons.push("empty mode");
    } else {
      item.keyword.mode = hasQueryText ? "query" : "poll";
      repaired = true;
      repairReasons.push(`invalid mode '${item.keyword.mode}'`);
    }
    if (typeof item.keyword.filter !== "string") {
      item.keyword.filter = "";
      repaired = true;
      repairReasons.push("non-string filter");
    }
    if (typeof item.keyword.query !== "string" && item.keyword.query !== null) {
      item.keyword.query = null;
      repaired = true;
      repairReasons.push("invalid query");
    }
    if (repaired) {
      console.log("[normalize] ensureItemKeywordConfig:", repairReasons.join(", "));
    }
    return item.keyword;
  }

  function setStatus(text, kind = "") {
    statusEl.textContent = text;
    statusEl.className = `status-chip ${kind}`.trim();
  }

  function showError(message) {
    setStatus(message, "error");
    console.error(`[Error] ${message}`);
  }

  function showSuccess(message) {
    setStatus(message, "ok");
  }

  function showWarning(message) {
    setStatus(message, "warning");
  }

  function updatePingSaveButtonState() {
    const hasPings = !!state && Array.isArray(state.pings) && state.pings.length > 0;
    const hasValidationErrors = hasPings && selectedPingIndex >= 0
      ? validatePingForSave(state.pings[selectedPingIndex], selectedPingIndex).length > 0
      : false;
    btnSavePingEl.disabled = !hasPings || !hasPendingPingChanges || hasValidationErrors;
    if (hasValidationErrors) {
      btnSavePingEl.textContent = "Fix Validation Errors";
    } else {
      btnSavePingEl.textContent = hasPendingPingChanges ? "Save Ping Changes" : "All Changes Saved";
    }

    if (pingSaveDockEl) {
      pingSaveDockEl.classList.toggle("visible", hasPendingPingChanges);
      pingSaveDockEl.setAttribute("aria-hidden", hasPendingPingChanges ? "false" : "true");
    }

    const btnDiscardEl = document.getElementById("btnDiscard");
    if (btnDiscardEl) {
      btnDiscardEl.disabled = !hasPendingPingChanges;
    }
  }

  function updateBlocklistSaveState() {
    const hasChanges = JSON.stringify(state.blocklist) !== JSON.stringify(originalBlocklist);
    btnSaveBlocklist.disabled = !hasChanges;
    btnSaveBlocklist.textContent = hasChanges ? "Save Blocklist Changes" : "All Changes Saved";
    btnDiscardBlocklist.style.display = hasChanges ? "inline-flex" : "none";
    toggleSaveDockVisibility(btnSaveBlocklist, hasChanges);
  }

  function isRegexBlocklistEntry(value) {
    return String(value || "").toLowerCase().startsWith("regexp::");
  }

  function stripRegexPrefix(value) {
    return String(value || "").replace(/^regexp::/i, "");
  }

  function updateBlocklistAddHint() {
    if (!blocklistAddHintEl || !blocklistAddModeEl) return;
    blocklistAddHintEl.textContent = blocklistAddModeEl.value === "regex"
      ? "Saved as a regex pattern."
      : "Saved as plaintext.";
  }

  function syncBlocklistDialogModeFromValue() {
    if (!blocklistAddModeEl || !blocklistAddValueEl) return;
    const raw = blocklistAddValueEl.value.trim();
    const shouldBeRegex = isRegexBlocklistEntry(raw);
    const shouldBePlain = raw !== "" && !shouldBeRegex;
    if (shouldBeRegex && blocklistAddModeEl.value !== "regex") {
      blocklistAddModeEl.value = "regex";
      blocklistAddValueEl.value = stripRegexPrefix(raw);
      updateBlocklistAddHint();
    } else if (shouldBePlain && blocklistAddModeEl.value !== "plain") {
      blocklistAddModeEl.value = "plain";
      updateBlocklistAddHint();
    }
  }

  function applyBlocklistDialogModeToggle() {
    if (!blocklistAddModeEl || !blocklistAddValueEl) return;
    blocklistAddValueEl.value = stripRegexPrefix(blocklistAddValueEl.value).trim();
    updateBlocklistAddHint();
  }

  function createSingleSelect(selectedValue, options, onChange) {
    const container = document.createElement("div");
    container.className = "custom-select";

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger";

    const menu = document.createElement("div");
    menu.className = "select-menu";

    const normalize = (value) => String(value ?? "");
    let currentValue = normalize(selectedValue);

    const getLabel = (value) => {
      const found = options.find((opt) => normalize(opt.value) === normalize(value));
      return found ? found.label : (options[0]?.label ?? "");
    };

    const syncTrigger = () => {
      trigger.textContent = getLabel(currentValue);
    };

    options.forEach((opt) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "tonal";
      item.style.width = "100%";
      item.style.textAlign = "left";
      item.textContent = opt.label;
      item.addEventListener("click", (e) => {
        e.stopPropagation();
        currentValue = normalize(opt.value);
        syncTrigger();
        menu.classList.remove("open");
        onChange(currentValue);
      });
      menu.appendChild(item);
    });

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      document.querySelectorAll(".select-menu").forEach((m) => {
        if (m !== menu) m.classList.remove("open");
      });
      menu.classList.toggle("open");
    });

    syncTrigger();
    container.appendChild(trigger);
    container.appendChild(menu);
    return { container, setValue: (v) => { currentValue = normalize(v); syncTrigger(); } };
  }

  function openBlocklistAddDialog() {
    if (!blocklistAddOverlayEl || !blocklistAddModeEl || !blocklistAddValueEl) return;
    blocklistAddModeEl.value = "plain";
    if (blocklistAddModeDropdown) {
      blocklistAddModeDropdown.setValue("plain");
    }
    blocklistAddValueEl.value = "";
    updateBlocklistAddHint();
    blocklistAddOverlayEl.classList.add("open");
    blocklistAddOverlayEl.setAttribute("aria-hidden", "false");
    setTimeout(() => blocklistAddValueEl.focus(), 0);
  }

  function closeBlocklistAddDialog() {
    if (!blocklistAddOverlayEl) return;
    blocklistAddOverlayEl.classList.remove("open");
    blocklistAddOverlayEl.setAttribute("aria-hidden", "true");
  }

  function addBlocklistFromDialog() {
    if (!blocklistAddModeEl || !blocklistAddValueEl) return;
    const raw = blocklistAddValueEl.value.trim();
    if (!raw) {
      setStatus("Please enter a blocklist keyword.", "error");
      return;
    }

    const normalizedCore = stripRegexPrefix(raw).trim();
    const finalValue = blocklistAddModeEl.value === "regex"
      ? `regexp::${normalizedCore}`
      : normalizedCore;

    state.blocklist.push(finalValue);
    renderBlocklist();
    updateBlocklistSaveState();
    closeBlocklistAddDialog();
    setStatus("Blocklist keyword added.", "ok");
  }

  function updateRolesSaveState() {
    const hasChanges = JSON.stringify(state.self_roles) !== JSON.stringify(originalState.self_roles);
    btnSaveRoles.disabled = !hasChanges;
    btnSaveRoles.textContent = hasChanges ? "Save Role Picker Changes" : "All Changes Saved";
    btnDiscardRoles.style.display = hasChanges ? "inline-flex" : "none";
    toggleSaveDockVisibility(btnSaveRoles, hasChanges);
  }

  function updateSettingsSaveState() {
    const s1 = { ...state };
    const s2 = { ...originalState };
    // Exclude pings, blocklist, self_roles, editor_metadata for comparison
    delete s1.pings; delete s1.blocklist; delete s1.self_roles; delete s1.editor_metadata;
    delete s2.pings; delete s2.blocklist; delete s2.self_roles; delete s2.editor_metadata;
    const hasChanges = JSON.stringify(s1) !== JSON.stringify(s2);
    btnSaveSettings.disabled = !hasChanges;
    btnSaveSettings.textContent = hasChanges ? "Save Settings" : "All Changes Saved";
    btnDiscardSettings.style.display = hasChanges ? "inline-flex" : "none";
    toggleSaveDockVisibility(btnSaveSettings, hasChanges);
  }

  function toggleSaveDockVisibility(primaryButtonEl, show) {
    if (!primaryButtonEl) return;
    const dock = primaryButtonEl.closest(".save-dock");
    if (!dock) return;
    dock.classList.add("is-collapsible");
    dock.classList.toggle("visible", !!show);
    dock.setAttribute("aria-hidden", show ? "false" : "true");
  }

  async function discardChanges() {
    if (!hasPendingPingChanges) return;
    const confirmed = await confirmAction(
      "Discard Changes",
      "Revert all unsaved changes for this ping to the last saved state?",
      "Discard",
      "danger",
      false // don't close on confirm
    );

    if (confirmed) {
      setModalLoading(true);
      const btnDiscard = document.getElementById("btnDiscard");
      if (btnDiscard) btnDiscard.classList.add("loading");
      
      send({ action: ACTION_GET_STATE });
      setStatus("Discarding changes...", "ok");
    }
  }

  function deepEqualForDirtyCheck(a, b, path = "") {
    if (a === b) return true;

    const aIsArray = Array.isArray(a);
    const bIsArray = Array.isArray(b);
    if (aIsArray || bIsArray) {
      if (!aIsArray || !bIsArray) return false;
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i += 1) {
        if (!deepEqualForDirtyCheck(a[i], b[i], `${path}[${i}]`)) {
          return false;
        }
      }
      return true;
    }

    const aIsObj = a && typeof a === "object";
    const bIsObj = b && typeof b === "object";
    if (aIsObj || bIsObj) {
      if (!aIsObj || !bIsObj) return false;

      const aKeys = Object.keys(a).sort();
      const bKeys = Object.keys(b).sort();

      if (aKeys.length !== bKeys.length) return false;
      for (let i = 0; i < aKeys.length; i += 1) {
        if (aKeys[i] !== bKeys[i]) return false;
        const key = aKeys[i];
        const nextPath = path ? `${path}.${key}` : key;
        if (!deepEqualForDirtyCheck(a[key], b[key], nextPath)) {
          return false;
        }
      }
      return true;
    }

    return Object.is(a, b);
  }

  function markPingChanged() {
    if (!state || !originalState) {
      hasPendingPingChanges = false;
    } else {
      const currentPing = state.pings[selectedPingIndex];
      const origPing = originalState.pings[selectedPingIndex];
      const currentMeta = state.editor_metadata?.pings?.[selectedPingIndex] || null;
      const origMeta = originalState.editor_metadata?.pings?.[selectedPingIndex] || null;

      const pingEqual = deepEqualForDirtyCheck(currentPing, origPing);
      const metaEqual = deepEqualForDirtyCheck(currentMeta, origMeta);
      hasPendingPingChanges = !pingEqual || !metaEqual;

      if (
        !hasPendingPingChanges &&
        currentPing &&
        origPing &&
        currentPing.price_ranges_last_updated !== origPing.price_ranges_last_updated
      ) {
        currentPing.price_ranges_last_updated = origPing.price_ranges_last_updated;
        const input = document.querySelector('input[data-field="price_ranges_last_updated"]');
        if (input) {
          const date = new Date(origPing.price_ranges_last_updated);
          input.value = date.toISOString().slice(0, 16);
        }
      }
    }
    updatePingSaveButtonState();
  }

  function touchSelectedPingTimestampIfNeeded() {
    if (!hasPendingPingChanges) return;
    if (!state || !state.pings || !state.pings.length) return;

    const currentPing = state.pings[selectedPingIndex];
    const originalPing = originalState?.pings?.[selectedPingIndex];
    if (!currentPing || !originalPing || typeof currentPing !== "object") return;

    const currentKeywords = Array.isArray(currentPing.items) ? currentPing.items : [];
    const originalKeywords = Array.isArray(originalPing.items) ? originalPing.items : [];

    let shouldTouch = currentKeywords.length !== originalKeywords.length;

    if (!shouldTouch) {
      for (let i = 0; i < currentKeywords.length; i += 1) {
        const currentKeyword = currentKeywords[i] || {};
        const originalKeyword = originalKeywords[i] || {};

        const minChanged = !Object.is(currentKeyword.min_price ?? null, originalKeyword.min_price ?? null);
        const maxChanged = !Object.is(currentKeyword.max_price ?? null, originalKeyword.max_price ?? null);
        const targetChanged = !Object.is(currentKeyword.target_price ?? null, originalKeyword.target_price ?? null);
        const rangesChanged = !deepEqualForDirtyCheck(
          currentKeyword.deal_ranges ?? null,
          originalKeyword.deal_ranges ?? null,
        );

        if (minChanged || maxChanged || targetChanged || rangesChanged) {
          shouldTouch = true;
          break;
        }
      }
    }

    if (shouldTouch) {
      touchPriceRangesLastUpdated(currentPing);
    }
  }

  function touchPriceRangesLastUpdated(ping) {
    if (!ping || typeof ping !== "object") return;
    ping.price_ranges_last_updated = new Date().toISOString();

    // Keep the visible datetime-local input in sync (this panel doesn't always re-render).
    const input = document.querySelector('input[data-field="price_ranges_last_updated"]');
    if (input) {
      const date = new Date(ping.price_ranges_last_updated);
      input.value = date.toISOString().slice(0, 16);
    }
  }

  function markPingSaved() {
    originalState = JSON.parse(JSON.stringify(state));
    hasPendingPingChanges = false;
    updatePingSaveButtonState();
    updateBlocklistSaveState();
  }

  function openConfirmDialog(title, message, confirmLabel = "Confirm", style = "primary") {
    confirmTitleEl.textContent = title;
    confirmBodyEl.textContent = message;
    confirmOkBtnEl.textContent = confirmLabel;
    confirmOkBtnEl.className = style;
    confirmOverlayEl.classList.add("open");
    confirmOverlayEl.setAttribute("aria-hidden", "false");
    confirmOkBtnEl.focus();
  }

  function closeConfirmDialog() {
    confirmOverlayEl.classList.remove("open");
    confirmOverlayEl.setAttribute("aria-hidden", "true");
  }

  function resolveConfirm(value) {
    if (confirmResolver) {
      confirmResolver(value);
      confirmResolver = null;
    }
  }

  function setModalLoading(loading) {
    if (loading) {
      confirmModalEl.classList.add("loading");
    } else {
      confirmModalEl.classList.remove("loading");
      closeConfirmDialog();
    }
  }

  function confirmAction(title, message, confirmLabel = "Confirm", style = "primary", closeOnConfirm = true) {
    return new Promise((resolve) => {
      confirmResolver = (val) => {
        if (val && !closeOnConfirm) {
          // Keep open for loading state
        } else {
          closeConfirmDialog();
        }
        resolve(val);
      };
      openConfirmDialog(title, message, confirmLabel, style);
    });
  }

  function buildConfigPayloadForSave() {
    const payload = JSON.parse(JSON.stringify(state || {}));
    if (Array.isArray(payload.pings)) {
      payload.pings.forEach((ping) => {
        if (!ping || !Array.isArray(ping.items)) return;
        ping.items.forEach((item) => {
          if (!item || typeof item !== "object") return;
          if (!item.keyword || typeof item.keyword !== "object") {
            item.keyword = { mode: "poll", filter: "", query: null };
          }
          const queryText = typeof item.keyword.query === "string" ? item.keyword.query.trim() : "";
          const modeValue = String(item.keyword.mode || "").trim().toLowerCase();
          if (!modeValue) {
            item.keyword.mode = queryText ? "query" : "poll";
          } else if (modeValue !== "poll" && modeValue !== "query") {
            item.keyword.mode = queryText ? "query" : "poll";
          } else {
            item.keyword.mode = modeValue;
          }
        });
      });
    }
    delete payload.blocklist;
    delete payload.global_blocklist;
    delete payload.editor_metadata;
    return payload;
  }

  function buildLcsDiff(beforeLines, afterLines) {
    const n = beforeLines.length;
    const m = afterLines.length;
    const dp = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));

    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        if (beforeLines[i] === afterLines[j]) {
          dp[i][j] = dp[i + 1][j + 1] + 1;
        } else {
          dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
    }

    const out = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (beforeLines[i] === afterLines[j]) {
        out.push({ type: "ctx", left: i + 1, right: j + 1, text: beforeLines[i] });
        i += 1;
        j += 1;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        out.push({ type: "del", left: i + 1, right: null, text: beforeLines[i] });
        i += 1;
      } else {
        out.push({ type: "add", left: null, right: j + 1, text: afterLines[j] });
        j += 1;
      }
    }
    while (i < n) {
      out.push({ type: "del", left: i + 1, right: null, text: beforeLines[i] });
      i += 1;
    }
    while (j < m) {
      out.push({ type: "add", left: null, right: j + 1, text: afterLines[j] });
      j += 1;
    }
    return out;
  }

  function buildContextDiffHtml(beforeObj, afterObj, contextLines = 2) {
    const before = JSON.stringify(beforeObj, null, 2).split("\n");
    const after = JSON.stringify(afterObj, null, 2).split("\n");
    const diff = buildLcsDiff(before, after);
    const changedIndexes = [];
    diff.forEach((line, index) => {
      if (line.type !== "ctx") changedIndexes.push(index);
    });

    if (changedIndexes.length === 0) {
      return '<span class="save-diff-line ctx">No JSON changes detected.</span>';
    }

    const keep = new Set();
    changedIndexes.forEach((idx) => {
      for (let i = Math.max(0, idx - contextLines); i <= Math.min(diff.length - 1, idx + contextLines); i++) {
        keep.add(i);
      }
    });

    const rendered = [];
    let inHunk = false;
    for (let idx = 0; idx < diff.length; idx++) {
      if (!keep.has(idx)) {
        inHunk = false;
        continue;
      }
      if (!inHunk) {
        const line = diff[idx];
        const left = line.left || 0;
        const right = line.right || 0;
        rendered.push(`<span class="save-diff-line hunk">@@ -${left}, +${right} @@</span>`);
        inHunk = true;
      }
      const line = diff[idx];
      const prefix = line.type === "add" ? "+" : line.type === "del" ? "-" : " ";
      rendered.push(
        `<span class="save-diff-line ${line.type}">${prefix} ${escapeHtml(line.text)}</span>`
      );
    }

    return rendered.join("\n");
  }

  function openSaveDiffDialog(payload) {
    const beforePayload = JSON.parse(JSON.stringify(originalState || {}));
    delete beforePayload.blocklist;
    delete beforePayload.global_blocklist;
    delete beforePayload.editor_metadata;
    saveDiffPreEl.innerHTML = buildContextDiffHtml(beforePayload, payload.parsed || {});
    pendingSavePayload = payload;
    saveDiffOverlayEl.classList.add("open");
    saveDiffOverlayEl.setAttribute("aria-hidden", "false");
  }

  function closeSaveDiffDialog() {
    saveDiffOverlayEl.classList.remove("open");
    saveDiffOverlayEl.setAttribute("aria-hidden", "true");
    pendingSavePayload = null;
  }

  function send(payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showError("WebSocket is not connected");
      return false;
    }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}/ws`);

    ws.addEventListener("open", () => {
      setStatus("Connected", "ok");
      send({ action: ACTION_GET_STATE });
    });

    ws.addEventListener("close", () => {
      setStatus("Disconnected. Retrying...");
      setTimeout(connect, 1000);
    });

    ws.addEventListener("error", () => {
      setStatus("Socket error", "error");
    });

    ws.addEventListener("message", (event) => {
      try {
        const message = JSON.parse(event.data);
        handleMessage(message);
      } catch (err) {
        showError(`Invalid message: ${err}`);
      }
    });
  }

  const arrayEditorOverlayEl = document.getElementById("arrayEditorOverlay");
  const arrayEditorTitleEl = document.getElementById("arrayEditorTitle");
  const arrayItemsListEl = document.getElementById("arrayItemsList");
  const arrayNewItemInputEl = document.getElementById("arrayNewItemInput");
  const btnArrayAddItemEl = document.getElementById("btnArrayAddItem");
  const btnArrayCloseEl = document.getElementById("btnArrayClose");

  // Auto-generate modal elements
  const autoGenerateOverlayEl = document.getElementById("autoGenerateOverlay");
  const autoGenerateTitleEl = document.getElementById("autoGenerateTitle");
  const autoGenerateModalEl = document.getElementById("autoGenerateModal");
  const autoComponentTypeEl = document.getElementById("autoComponentType");
  const autoComponentFieldsGridEl = document.getElementById("autoComponentFieldsGrid");
  const autoMinPriceEl = document.getElementById("autoMinPrice");
  const autoTargetPriceEl = document.getElementById("autoTargetPrice");
  const autoMaxPriceEl = document.getElementById("autoMaxPrice");
  const btnAutoGenerateCancelEl = document.getElementById("btnAutoGenerateCancel");
  const btnAutoGenerateApplyEl = document.getElementById("btnAutoGenerateApply");
  const filterGenerateOverlayEl = document.getElementById("filterGenerateOverlay");
  const filterComponentTypeEl = document.getElementById("filterComponentType");
  const filterComponentFieldsGridEl = document.getElementById("filterComponentFieldsGrid");
  const btnFilterGenerateCancelEl = document.getElementById("btnFilterGenerateCancel");
  const btnFilterGenerateApplyEl = document.getElementById("btnFilterGenerateApply");
  const saveDiffOverlayEl = document.getElementById("saveDiffOverlay");
  const saveDiffPreEl = document.getElementById("saveDiffPre");
  const btnSaveDiffCancelEl = document.getElementById("btnSaveDiffCancel");
  const btnSaveDiffConfirmEl = document.getElementById("btnSaveDiffConfirm");

  let arrayResolver = null;
  let currentArrayList = [];
  let currentArrayIsNumeric = false;
  let currentKeywordIndex = null;
  let pendingSavePayload = null;
  let ebayCategories = [];
  let autoGenerateContext = { conversion_mode: false, item_mode: "poll" };

  const AUTO_COMPONENT_TYPES = [
    { value: "nvidia_gpu", label: "NVIDIA GPU" },
    { value: "amd_gpu", label: "AMD GPU" },
    { value: "amd_cpu", label: "AMD CPU" },
    { value: "ram", label: "RAM" },
    { value: "nvme_ssd", label: "NVMe SSD" },
    { value: "custom", label: "Custom / Manual" },
  ];

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function getDefaultComponentData(componentType) {
    const defaults = {
      nvidia_gpu: { brand: "RTX", model: "", variant: "normal", vram: "" },
      amd_gpu: { model: "", variant: "normal" },
      amd_cpu: { ryzen: "5", model: "", suffix: "" },
      ram: { capacity: "", ddr: "DDR5", speed: "" },
      nvme_ssd: { capacity_mode: "gb", gb: "", tb: "" },
      custom: {},
    };
    return cloneJson(defaults[componentType] || {});
  }

  const autoComponentState = {
    nvidia_gpu: getDefaultComponentData("nvidia_gpu"),
    amd_gpu: getDefaultComponentData("amd_gpu"),
    amd_cpu: getDefaultComponentData("amd_cpu"),
    ram: getDefaultComponentData("ram"),
    nvme_ssd: getDefaultComponentData("nvme_ssd"),
    custom: getDefaultComponentData("custom"),
  };

  const NVME_EXCLUSIONS = [
    "\\bNotebook\\b", "\\bDesktop\\b", "\\bPC\\b", "\\bDDR\\d\\b", "\\bRAM\\b", "\\bHDD\\b",
    "\\bHard\\s*Disk\\b", "\\bHard\\s*Drive\\b", "\\bExternal\\b", "\\bUSB\\b", "\\bPortable\\b",
    "\\b\\d{4}\\s*RPM\\b", "\\beMMC\\b", "\\bflash\\s*drive\\b", "\\bsd\\s*card\\b",
    "\\bmemory\\s*card\\b", "\\bmemory\\s*stick\\b", "\\b2230\\b", "\\b2242\\b", "2\\.5", "3\\.5", "SATA"
  ].join("|");

  const NVME_KEYWORDS = [
    "SSD", "NVMe", "M\\.2", "Solid\\s*State", "SDD"
  ].join("|");

  function openArrayEditor(title, initialList, isNumeric, onSave) {
    arrayEditorTitleEl.textContent = title;
    currentArrayList = [...initialList];
    currentArrayIsNumeric = isNumeric;
    arrayNewItemInputEl.value = "";
    arrayNewItemInputEl.type = isNumeric ? "number" : "text";
    
    renderArrayItems();
    
    arrayEditorOverlayEl.classList.add("open");
    arrayEditorOverlayEl.setAttribute("aria-hidden", "false");
    
    arrayResolver = onSave;
  }

  function renderArrayItems() {
    arrayItemsListEl.innerHTML = "";
    currentArrayList.forEach((val, index) => {
      const chip = document.createElement("div");
      chip.className = "array-chip";
      chip.textContent = val;
      
      const remove = document.createElement("span");
      remove.className = "remove-item";
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        currentArrayList.splice(index, 1);
        renderArrayItems();
      });
      
      chip.appendChild(remove);
      arrayItemsListEl.appendChild(chip);
    });
  }

  function addArrayItem() {
    const val = arrayNewItemInputEl.value.trim();
    if (!val) return;
    
    let processed = val;
    if (currentArrayIsNumeric) {
      processed = Number(val);
      if (isNaN(processed)) return;
    }
    
    if (!currentArrayList.includes(processed)) {
      currentArrayList.push(processed);
      renderArrayItems();
      arrayNewItemInputEl.value = "";
      arrayNewItemInputEl.focus();
    }
  }

  function closeArrayEditor() {
    if (arrayResolver) {
      arrayResolver(currentArrayList);
    }
    arrayEditorOverlayEl.classList.remove("open");
    arrayEditorOverlayEl.setAttribute("aria-hidden", "true");
  }

  function inferComponentTypeFromKeyword(keywordValue) {
    const normalized = String(keywordValue || "").toLowerCase();
    if (!normalized) return "nvidia_gpu";
    if (normalized.includes("ryzen")) return "amd_cpu";
    if (normalized.includes("rtx") || normalized.includes("gtx")) return "nvidia_gpu";
    if (normalized.includes("rx") || normalized.includes("xtx")) return "amd_gpu";
    if (normalized.includes("ddr")) return "ram";
    if (normalized.includes("nvme") || normalized.includes("m\\.2") || normalized.includes("m.2") || normalized.includes("solid state") || normalized.includes("ssd")) {
      return "nvme_ssd";
    }
    return "custom";
  }

  function setAutoKeywordReadonlyByType(componentType) {
    return componentType === "custom";
  }

  function getSuggestedMinPrice(targetPriceRaw) {
    const targetPrice = Number(targetPriceRaw) || 0;
    let minPrice = 0;
    let formula = "";

    if (targetPrice < 100) {
      minPrice = Math.floor(targetPrice * 0.15);
      formula = "15% of target";
    } else if (targetPrice < 500) {
      minPrice = Math.floor(targetPrice * 0.25);
      formula = "25% of target";
    } else {
      minPrice = Math.floor(targetPrice * 0.4);
      formula = "40% of target";
    }

    const remainder = minPrice % 5;
    if (remainder === 1 || remainder === 2) {
      minPrice -= remainder;
    } else if (remainder !== 0) {
      minPrice += (5 - remainder);
    }

    return { minPrice, formula };
  }

  function updateMinPriceHint() {
    const hintEl = document.getElementById("minPriceHint");
    if (!hintEl) return;
    const { minPrice, formula } = getSuggestedMinPrice(autoTargetPriceEl.value);
    hintEl.textContent = `Suggested: $${minPrice}${formula ? ` (${formula})` : ""}`;
  }

  function updateMaxPriceHint() {
    const hintEl = document.getElementById("maxPriceHint");
    if (!hintEl) return;
    const targetPrice = Number(autoTargetPriceEl.value) || 0;
    const componentType = autoComponentTypeEl ? autoComponentTypeEl.value : "custom";
    const suggestedMinPrice = getSuggestedMinPrice(targetPrice).minPrice;
    const ranges = calculateDealRanges(suggestedMinPrice, targetPrice, componentType);
    hintEl.textContent = `Suggested: $${ranges.max_price}`;
  }

  function ensureAutoComponentTypeOptions() {
    if (!autoComponentTypeEl || autoComponentTypeEl.options.length > 0) return;
    AUTO_COMPONENT_TYPES.forEach((component) => {
      const option = document.createElement("option");
      option.value = component.value;
      option.textContent = component.label;
      autoComponentTypeEl.appendChild(option);
    });
  }

  function renderAutoComponentFields() {
    if (!autoComponentTypeEl || !autoComponentFieldsGridEl) return;
    const componentType = autoComponentTypeEl.value;
    const values = autoComponentState[componentType] || {};

    autoComponentFieldsGridEl.innerHTML = "";

    function addField({ key, label, type = "text", placeholder = "", options = [], cls = "half" }) {
      const wrapper = document.createElement("div");
      wrapper.className = `field ${cls}`;

      const fieldLabel = document.createElement("label");
      fieldLabel.textContent = label;
      wrapper.appendChild(fieldLabel);

      let input;
      if (type === "select") {
        input = document.createElement("select");
        options.forEach((option) => {
          const optionEl = document.createElement("option");
          if (typeof option === "string") {
            optionEl.value = option;
            optionEl.textContent = option;
          } else {
            optionEl.value = option.value;
            optionEl.textContent = option.label;
          }
          input.appendChild(optionEl);
        });
      } else {
        input = document.createElement("input");
        input.type = type;
        if (placeholder) {
          input.placeholder = placeholder;
        }
      }

      input.value = values[key] ?? "";
      input.addEventListener("input", () => {
        values[key] = input.value;
        if (key === "variant" || key === "capacity_mode") {
          renderAutoComponentFields();
        } else {
          updateAutoGeneratedKeywordPreview();
        }
      });
      input.addEventListener("change", () => {
        values[key] = input.value;
        if (key === "variant" || key === "capacity_mode") {
          renderAutoComponentFields();
        } else {
          updateAutoGeneratedKeywordPreview();
        }
      });

      wrapper.appendChild(input);
      autoComponentFieldsGridEl.appendChild(wrapper);
    }

    if (componentType === "amd_cpu") {
      addField({
        key: "ryzen",
        label: "Ryzen Series",
        type: "select",
        options: ["3", "5", "7", "9"]
      });
      addField({ key: "model", label: "CPU Model", placeholder: "e.g., 3600, 7800" });
      addField({ key: "suffix", label: "Suffix (Optional)", placeholder: "e.g., X, X3D" });
    } else if (componentType === "nvidia_gpu") {
      addField({
        key: "brand",
        label: "GPU Brand",
        type: "select",
        options: ["RTX", "GTX"]
      });
      addField({ key: "model", label: "GPU Model", placeholder: "e.g., 3080, 4070, 5080" });
      addField({
        key: "variant",
        label: "Variant",
        type: "select",
        options: [
          { value: "normal", label: "Normal" },
          { value: "ti", label: "Ti" },
          { value: "super", label: "SUPER" },
          { value: "ti_super", label: "Ti SUPER" }
        ]
      });
      if (values.variant === "normal") {
        addField({ key: "vram", label: "VRAM GB (Optional)", type: "number", placeholder: "e.g., 12" });
      }
    } else if (componentType === "amd_gpu") {
      addField({ key: "model", label: "GPU Model", placeholder: "e.g., 6600, 7800, 9070" });
      addField({
        key: "variant",
        label: "Variant",
        type: "select",
        options: [
          { value: "normal", label: "Normal" },
          { value: "xt", label: "XT" },
          { value: "xtx", label: "XTX" }
        ]
      });
    } else if (componentType === "ram") {
      addField({ key: "capacity", label: "Capacity (GB)", placeholder: "e.g., 16" });
      addField({ key: "ddr", label: "DDR Type", placeholder: "e.g., DDR4, DDR5" });
      addField({ key: "speed", label: "Speed (MHz)", placeholder: "e.g., 3200, 6000" });
    } else if (componentType === "nvme_ssd") {
      addField({
        key: "capacity_mode",
        label: "Capacity Mode",
        type: "select",
        options: [
          { value: "gb", label: "GB only" },
          { value: "tb", label: "TB only" },
          { value: "gb_tb", label: "GB or TB" }
        ]
      });
      if (values.capacity_mode === "gb" || values.capacity_mode === "gb_tb") {
        addField({ key: "gb", label: "GB Value / Regex", placeholder: "e.g., 512 or (?:256|512)" });
      }
      if (values.capacity_mode === "tb" || values.capacity_mode === "gb_tb") {
        addField({ key: "tb", label: "TB Value / Regex", placeholder: "e.g., 1 or (?:1|2)" });
      }
    } else if (componentType === "custom") {
      const hintWrap = document.createElement("div");
      hintWrap.className = "field full";
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Custom mode keeps the filter field editable.";
      hintWrap.appendChild(hint);
      autoComponentFieldsGridEl.appendChild(hintWrap);
    }

    updateAutoGeneratedKeywordPreview();
    updateMaxPriceHint();
  }

  function generateKeywordFromComponent(componentType, componentData = null, manualKeyword = "", manualFriendlyName = "") {
    const values = componentData && typeof componentData === "object"
      ? componentData
      : (autoComponentState[componentType] || {});

    if (componentType === "custom") {
      return {
        keyword: String(manualKeyword || "").trim(),
        friendlyName: String(manualFriendlyName || "").trim() || "Custom Keyword"
      };
    }

    if (componentType === "amd_cpu") {
      const ryzen = String(values.ryzen || "").trim();
      const model = String(values.model || "").trim();
      const suffix = String(values.suffix || "").trim();
      if (!ryzen || !model) {
        return { error: "AMD CPU requires Ryzen series and model." };
      }
      const keyword = suffix
        ? `regexp::(?:\\b(?:R|Ryzen)[\\s-]*${ryzen}[\\s-]*${model}[\\s-]*${suffix}\\b(?![a-zA-Z0-9]))`
        : `regexp::(?:\\b(?:R|Ryzen)[\\s-]*${ryzen}[\\s-]*${model}\\b(?![a-zA-Z]))`;
      return {
        keyword,
        friendlyName: `Ryzen ${ryzen} ${model}${suffix ? suffix : ""}`
      };
    }

    if (componentType === "nvidia_gpu") {
      const brand = String(values.brand || "RTX").trim().toUpperCase();
      const model = String(values.model || "").trim();
      const variant = String(values.variant || "normal");
      const vram = String(values.vram || "").trim();
      if (!model) {
        return { error: "NVIDIA GPU requires a model." };
      }
      if (variant !== "normal" && vram) {
        return { error: "VRAM can only be used with normal NVIDIA models (non-Ti, non-SUPER)." };
      }

      let keyword;
      if (variant === "ti_super") {
        keyword = `regexp::(?:\\b(?:${brand}[\\s-]*)?${model}[\\s-]*Ti[\\s-]*SUPER\\b)`;
      } else if (variant === "ti") {
        keyword = `regexp::(?:\\b(?:${brand}[\\s-]*)?${model}[\\s-]*Ti\\b(?![\\s-]*SUPER\\b))`;
      } else if (variant === "super") {
        keyword = `regexp::(?:\\b(?:${brand}[\\s-]*)?${model}[\\s-]*SUPER\\b)`;
      } else if (vram) {
        keyword = `regexp::(?:\\b(?:${brand}[\\s-]*)?${model}\\b(?![\\s-]*(?:Ti|SUPER)\\b)[\\s-]+${vram}\\s?GB\\b)`;
      } else {
        keyword = `regexp::(?:\\b(?:${brand}[\\s-]*)?${model}\\b(?![\\s-]*(?:Ti|SUPER)\\b))`;
      }

      const suffix = variant === "ti_super" ? " Ti SUPER" : variant === "ti" ? " Ti" : variant === "super" ? " SUPER" : "";
      return {
        keyword,
        friendlyName: `${model}${suffix}${variant === "normal" && vram ? ` ${vram}GB` : ""}`
      };
    }

    if (componentType === "amd_gpu") {
      const model = String(values.model || "").trim();
      const variant = String(values.variant || "normal");
      if (!model) {
        return { error: "AMD GPU requires a model." };
      }
      let keyword;
      if (variant === "xt") {
        keyword = `regexp::(?:\\b(?:RX[\\s-]*)?${model}[\\s-]*XT\\b(?![\\s-]*XTX\\b))`;
      } else if (variant === "xtx") {
        keyword = `regexp::(?:\\b(?:RX[\\s-]*)?${model}[\\s-]*XTX\\b)`;
      } else {
        keyword = `regexp::(?:\\b(?:RX[\\s-]*)?${model}\\b(?![\\s-]*(?:XT|XTX)\\b))`;
      }
      return {
        keyword,
        friendlyName: `${model}${variant === "xt" ? " XT" : variant === "xtx" ? " XTX" : ""}`
      };
    }

    if (componentType === "ram") {
      const capacity = String(values.capacity || "").trim();
      const ddr = String(values.ddr || "").trim();
      const speed = String(values.speed || "").trim();
      if (!capacity || !ddr || !speed) {
        return { error: "RAM requires capacity, DDR type, and speed." };
      }
      return {
        keyword: `regexp::(?=.*(?:${capacity})[\\s_-]*(?:gigabytes|gigabyte|gib|gb|g\\b))(?=.*${ddr})(?=.*(?:${speed})).*`,
        friendlyName: `${capacity}GB ${ddr}${speed ? `-${speed}` : ""}`
      };
    }

    if (componentType === "nvme_ssd") {
      const mode = String(values.capacity_mode || "gb");
      const gb = String(values.gb || "").trim();
      const tb = String(values.tb || "").trim();

      if (mode === "gb" && !gb) {
        return { error: "NVMe SSD (GB mode) requires a GB value." };
      }
      if (mode === "tb" && !tb) {
        return { error: "NVMe SSD (TB mode) requires a TB value." };
      }
      if (mode === "gb_tb" && (!gb || !tb)) {
        return { error: "NVMe SSD (GB or TB mode) requires both GB and TB values." };
      }

      if (mode === "gb") {
        return {
          keyword: `regexp::^(?!.*(?:${NVME_EXCLUSIONS}))(?=.*(?:${gb}[\\s_-]*(?:GiB|GB|G\\b)))(?=.*(?:${NVME_KEYWORDS})).*`,
          friendlyName: `${gb}GB SSD`
        };
      }
      if (mode === "tb") {
        return {
          keyword: `regexp::^(?!.*(?:${NVME_EXCLUSIONS}))(?=.*(?:${tb}[\\s_-]*(?:TiB|TB|T\\b)))(?=.*(?:${NVME_KEYWORDS})).*`,
          friendlyName: `${tb}TB SSD`
        };
      }
      return {
        keyword: `regexp::^(?!.*(?:${NVME_EXCLUSIONS}))(?=.*(?:${gb}[\\s_-]*(?:GiB|GB|G\\b)|${tb}[\\s_-]*(?:TiB|TB|T\\b)))(?=.*(?:${NVME_KEYWORDS})).*`,
        friendlyName: `${gb}GB_TB SSD`
      };
    }

    return { error: "Unsupported component type." };
  }

  function updateAutoGeneratedKeywordPreview() {
    return;
  }

  function ensureFilterComponentTypeOptions() {
    if (!filterComponentTypeEl || filterComponentTypeEl.options.length > 0) return;
    AUTO_COMPONENT_TYPES.filter(component => component.value !== "custom").forEach((component) => {
      const option = document.createElement("option");
      option.value = component.value;
      option.textContent = component.label;
      filterComponentTypeEl.appendChild(option);
    });
  }

  function renderFilterComponentFields() {
    if (!filterComponentTypeEl || !filterComponentFieldsGridEl) return;
    const componentType = filterComponentTypeEl.value;
    const values = autoComponentState[componentType] || {};
    filterComponentFieldsGridEl.innerHTML = "";
    const addInput = (labelText, key, type = "text", cls = "third", options = null, placeholder = "") => {
      const wrapper = document.createElement("div");
      wrapper.className = `field ${cls}`;
      const label = document.createElement("label");
      label.textContent = labelText;
      wrapper.appendChild(label);
      let input;
      if (type === "select") {
        input = document.createElement("select");
        options.forEach((opt) => {
          const option = document.createElement("option");
          if (typeof opt === "string") {
            option.value = opt;
            option.textContent = opt;
          } else {
            option.value = opt.value;
            option.textContent = opt.label;
          }
          input.appendChild(option);
        });
      } else {
        input = document.createElement("input");
        input.type = type;
        if (placeholder) input.placeholder = placeholder;
      }
      input.value = values[key] ?? "";
      const eventName = type === "select" ? "change" : "input";
      input.addEventListener(eventName, () => {
        values[key] = input.value;
        autoComponentState[componentType] = values;
        if (key === "variant" || key === "capacity_mode") {
          renderFilterComponentFields();
        }
      });
      wrapper.appendChild(input);
      filterComponentFieldsGridEl.appendChild(wrapper);
    };

    if (componentType === "nvidia_gpu") {
      addInput("GPU Brand", "brand", "select", "third", ["RTX", "GTX"]);
      addInput("Model", "model", "text", "third", null, "e.g., 5070");
      addInput("Variant", "variant", "select", "third", [
        { value: "normal", label: "Normal" },
        { value: "ti", label: "Ti" },
        { value: "super", label: "SUPER" },
        { value: "ti_super", label: "Ti SUPER" },
      ]);
    } else if (componentType === "amd_gpu") {
      addInput("Model", "model", "text", "half", null, "e.g., 9070");
      addInput("Variant", "variant", "select", "half", [
        { value: "normal", label: "Normal" },
        { value: "xt", label: "XT" },
        { value: "xtx", label: "XTX" },
      ]);
    } else if (componentType === "amd_cpu") {
      addInput("Ryzen Series", "ryzen", "select", "third", ["3", "5", "7", "9"]);
      addInput("Model", "model", "text", "third", null, "e.g., 7800");
    } else if (componentType === "ram") {
      addInput("Capacity (GB)", "capacity", "number", "third");
      addInput("DDR Type", "ddr", "text", "third", null, "DDR5");
      addInput("Speed (MHz)", "speed", "number", "third");
    } else if (componentType === "nvme_ssd") {
      addInput("Capacity Mode", "capacity_mode", "select", "third", [
        { value: "gb", label: "GB only" },
        { value: "tb", label: "TB only" },
        { value: "gb_tb", label: "GB or TB" },
      ]);
      if (values.capacity_mode === "gb" || values.capacity_mode === "gb_tb") {
        addInput("GB Value / Regex", "gb", "text", "third", null, "e.g., 512");
      }
      if (values.capacity_mode === "tb" || values.capacity_mode === "gb_tb") {
        addInput("TB Value / Regex", "tb", "text", "third", null, "e.g., 1");
      }
    }
  }

  function openAutoGenerateModal(keywordIndex, options = {}) {
    ensureAutoComponentTypeOptions();
    autoGenerateContext = {
      conversion_mode: !!options.conversion_mode,
      item_mode: "poll",
    };
    if (autoGenerateTitleEl) {
      autoGenerateTitleEl.textContent = "Generate Deal Ranges";
    }
    currentKeywordIndex = keywordIndex;
    
    // Pre-fill with current keyword values if available
    const ping = state.pings[selectedPingIndex];
    const item = ping.items[keywordIndex];
    const keywordMeta = getKeywordMeta(selectedPingIndex, keywordIndex);
    const itemKeyword = ensureItemKeywordConfig(item);
    autoGenerateContext.item_mode = itemKeyword.mode || "poll";
    
    autoMinPriceEl.value = item.min_price !== null ? item.min_price : "";
    autoTargetPriceEl.value = item.target_price !== null ? item.target_price : "";
    autoMaxPriceEl.value = item.max_price !== null ? item.max_price : "";
    autoComponentState.nvidia_gpu.brand = String(itemKeyword.filter || "").toUpperCase().includes("GTX") ? "GTX" : "RTX";
    if (autoComponentTypeEl) {
      autoComponentTypeEl.value = options.force_component_type || inferComponentTypeFromKeyword(itemKeyword.filter || "") || "custom";
    }
    if (autoComponentTypeEl) {
      const prefillType = autoComponentTypeEl.value || "custom";
      let prefillData = null;
      if (options.prefill_component_data && typeof options.prefill_component_data === "object") {
        prefillData = cloneJson(options.prefill_component_data);
      } else if (keywordMeta.mode === "typed" && keywordMeta.component_type === prefillType && keywordMeta.component_data) {
        prefillData = cloneJson(keywordMeta.component_data);
      } else if (prefillType !== "custom") {
        prefillData = reverseParseComponentData(item, prefillType);
      }

      autoComponentState[prefillType] = {
        ...getDefaultComponentData(prefillType),
        ...(prefillData || {}),
      };
    }
    renderAutoComponentFields();
    
    // Calculate and display suggested min price
    updateMinPriceHint();
    updateMaxPriceHint();
    updateAutoGeneratedKeywordPreview();
    
    autoGenerateOverlayEl.classList.add("open");
    autoGenerateOverlayEl.setAttribute("aria-hidden", "false");
    autoTargetPriceEl.focus();
  }

  function closeAutoGenerateModal() {
    autoGenerateOverlayEl.classList.remove("open");
    autoGenerateOverlayEl.setAttribute("aria-hidden", "true");
    currentKeywordIndex = null;
  }

  function openFilterGenerateModal(keywordIndex, options = {}) {
    ensureFilterComponentTypeOptions();
    currentKeywordIndex = keywordIndex;
    const ping = state.pings[selectedPingIndex];
    const item = ping.items[keywordIndex];
    const keywordMeta = getKeywordMeta(selectedPingIndex, keywordIndex);
    const itemKeyword = ensureItemKeywordConfig(item);
    filterComponentTypeEl.value = options.force_component_type || inferComponentTypeFromKeyword(itemKeyword.filter || "") || "nvidia_gpu";
    const prefillType = filterComponentTypeEl.value || "nvidia_gpu";
    let prefillData = null;
    if (options.prefill_component_data && typeof options.prefill_component_data === "object") {
      prefillData = cloneJson(options.prefill_component_data);
    } else if (keywordMeta.mode === "typed" && keywordMeta.component_type === prefillType && keywordMeta.component_data) {
      prefillData = cloneJson(keywordMeta.component_data);
    } else if (prefillType && prefillType !== "custom") {
      prefillData = reverseParseComponentData(item, prefillType);
    }
    autoComponentState[prefillType] = {
      ...getDefaultComponentData(prefillType),
      ...(prefillData || {}),
    };
    renderFilterComponentFields();
    filterGenerateOverlayEl.classList.add("open");
    filterGenerateOverlayEl.setAttribute("aria-hidden", "false");
    filterComponentTypeEl.focus();
  }

  function closeFilterGenerateModal() {
    filterGenerateOverlayEl.classList.remove("open");
    filterGenerateOverlayEl.setAttribute("aria-hidden", "true");
    currentKeywordIndex = null;
  }

  function applyFilterGeneratedKeyword() {
    const componentType = filterComponentTypeEl ? filterComponentTypeEl.value : "custom";
    const generated = generateKeywordFromComponent(
      componentType,
      autoComponentState[componentType],
      "",
      "",
    );
    if (generated.error) {
      setStatus(generated.error, "error");
      return;
    }
    const keywordFilter = (generated.keyword || "").trim();
    if (!keywordFilter) {
      setStatus("Please provide enough data to generate a filter regex.", "error");
      return;
    }
    const ping = state.pings[selectedPingIndex];
    const kw = ping.items[currentKeywordIndex];
    const kwKeyword = ensureItemKeywordConfig(kw);
    const keywordMeta = getKeywordMeta(selectedPingIndex, currentKeywordIndex);
    kwKeyword.filter = keywordFilter;
    keywordMeta.mode = "typed";
    keywordMeta.component_type = componentType;
    keywordMeta.component_data = cloneJson(autoComponentState[componentType] || {});
    closeFilterGenerateModal();
    renderKeywords(ping);
    markPingChanged();
    setStatus("Filter applied from Filter Generator.", "ok");
  }

  function openCategorySelector(selectedIds, onChange) {
    // Load categories if not already loaded
    loadEbayCategories().then(() => {
      if (ebayCategories.length === 0) {
        showError("Failed to load eBay categories");
        return;
      }

      // Work on a copy so Cancel doesn't mutate the original array.
      const workingSelectedIds = (Array.isArray(selectedIds) ? selectedIds : [])
        .map(v => Number(v))
        .filter(v => Number.isFinite(v));

      // Create modal overlay
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      // Required for visibility: `.modal-overlay` is `display:none` unless it has `.open`
      overlay.classList.add("open");
      overlay.setAttribute("aria-hidden", "false");
      
      const modal = document.createElement("div");
      modal.className = "modal surface";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      
      const title = document.createElement("h2");
      title.textContent = "Select eBay Categories";
      
      // Search input
      const searchInput = document.createElement("input");
      searchInput.type = "text";
      searchInput.placeholder = "Search categories by name or ID...";
      searchInput.style.width = "100%";
      searchInput.style.marginBottom = "12px";
      searchInput.style.boxSizing = "border-box";
      
      // Results container (lazy loaded)
      const resultsContainer = document.createElement("div");
      resultsContainer.className = "category-results";
      
      // Show only first 100 results initially
      const MAX_INITIAL_RESULTS = 100;
      let displayedCount = 0;
      
      const renderResults = (searchTerm = "") => {
        resultsContainer.innerHTML = "";
        displayedCount = 0;
        
        const term = searchTerm.toLowerCase().trim();
        const filtered = ebayCategories.filter(cat => {
          if (!term) return true;
          return cat.name.toLowerCase().includes(term) || 
                 String(cat.id).includes(term);
        });

        // Keep selected items at the top (while preserving the original ordering
        // of the categories within each group).
        const selectedSet = new Set(workingSelectedIds);
        const selectedFirst = [];
        const unselected = [];
        filtered.forEach((cat) => {
          const idNum = Number(cat.id);
          (selectedSet.has(idNum) ? selectedFirst : unselected).push(cat);
        });
        const ordered = selectedFirst.concat(unselected);

        // Only render first MAX_INITIAL_RESULTS
        const toRender = ordered.slice(0, MAX_INITIAL_RESULTS);
        
        toRender.forEach(category => {
          const item = document.createElement("div");
          item.className = "category-item";
          item.dataset.id = String(category.id);

          const nameEl = document.createElement("span");
          nameEl.className = "category-name";
          nameEl.textContent = category.name;

          const idEl = document.createElement("span");
          idEl.className = "category-id";
          idEl.textContent = `ID: ${category.id}`;

          item.appendChild(nameEl);
          item.appendChild(idEl);

          const idNum = Number(category.id);
          const isSelected = workingSelectedIds.includes(idNum);
          if (isSelected) item.classList.add("selected");

          item.addEventListener("click", () => {
            const index = workingSelectedIds.indexOf(idNum);
            if (index > -1) {
              workingSelectedIds.splice(index, 1);
            } else {
              workingSelectedIds.push(idNum);
            }

            // Re-render so selected items stay grouped at the top.
            renderResults(searchInput.value);
          });

          resultsContainer.appendChild(item);
          displayedCount++;
        });
        
        // Show message if no results or if we're at limit
        if (filtered.length === 0) {
          const noResults = document.createElement("div");
          noResults.className = "muted";
          noResults.textContent = "No categories found";
          resultsContainer.appendChild(noResults);
        } else if (filtered.length > MAX_INITIAL_RESULTS) {
          const limitMsg = document.createElement("div");
          limitMsg.className = "hint";
          limitMsg.style.gridColumn = "span 12";
          limitMsg.style.marginTop = "8px";
          limitMsg.textContent = `Showing ${MAX_INITIAL_RESULTS} of ${filtered.length} results. Refine your search to see more.`;
          resultsContainer.appendChild(limitMsg);
        }
      };
      
      searchInput.addEventListener("input", () => {
        renderResults(searchInput.value);
      });
      
      // Initial render
      renderResults();
      
      // Buttons
      const buttonRow = document.createElement("div");
      buttonRow.className = "button-row modal-actions";
      
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "tonal";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", () => {
        overlay.remove();
      });
      
      const doneBtn = document.createElement("button");
      doneBtn.className = "primary";
      doneBtn.textContent = "Done";
      doneBtn.addEventListener("click", () => {
        overlay.remove();
        onChange([...workingSelectedIds]);
      });
      
      buttonRow.appendChild(cancelBtn);
      buttonRow.appendChild(doneBtn);
      
      modal.appendChild(title);
      modal.appendChild(searchInput);
      modal.appendChild(resultsContainer);
      modal.appendChild(buttonRow);
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
      
      // Close on overlay click
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) {
          overlay.remove();
        }
      });
      
      // Focus search input
      setTimeout(() => searchInput.focus(), 100);
    });
  }

  function calculateDealRanges(minPrice, targetPrice, componentType, forcedMaxPrice = null) {
    let maxPrice = targetPrice;

    if (componentType === "amd_cpu") {
      const spread = Math.floor(targetPrice / 20);
      maxPrice = targetPrice + (spread > 20 ? 20 : spread);
    } else if (componentType === "nvidia_gpu" || componentType === "amd_gpu") {
      // Piecewise spread for GPUs:
      // keep low-price cards from getting a tiny +$1/+2 ceiling,
      // while preserving the same cap behavior for expensive cards.
      let spread = Math.floor(targetPrice / 20);
      if (targetPrice < 50) {
        spread = Math.max(spread, 4);
      } else if (targetPrice < 100) {
        spread = Math.max(spread, 5);
      } else if (targetPrice < 200) {
        spread = Math.max(spread, 7);
      }
      maxPrice = targetPrice + (spread > 25 ? 25 : spread);
    } else {
      // RAM / NVMe / custom fallback
      maxPrice = targetPrice + Math.floor(targetPrice / 5);
      if (maxPrice - targetPrice < 10) {
        maxPrice = targetPrice + 10;
      } else if (maxPrice - targetPrice > 30) {
        maxPrice = targetPrice + 30;
      }
    }

    if (typeof forcedMaxPrice === "number" && Number.isFinite(forcedMaxPrice)) {
      maxPrice = Math.max(targetPrice, Math.max(minPrice, Math.floor(forcedMaxPrice)));
    }

    const greatEnd = targetPrice - 1;
    const fireStart = minPrice;
    const okEnd = maxPrice;
    const greatStart = targetPrice - 10;
    const fireEnd = greatStart - 1;
    const goodStart = greatEnd + 1;
    const goodEnd = goodStart + Math.floor((okEnd - goodStart) / 2);
    const okStart = goodEnd + 1;

    return {
      min_price: minPrice,
      max_price: maxPrice,
      target_price: targetPrice,
      deal_ranges: {
        fire_deal: { start: fireStart, end: fireEnd },
        great_deal: { start: greatStart, end: greatEnd },
        good_deal: { start: goodStart, end: goodEnd },
        ok_deal: { start: okStart, end: okEnd }
      }
    };
  }

  function applyAutoGeneratedRanges() {
    const componentType = autoComponentTypeEl ? autoComponentTypeEl.value : "custom";
    const generated = generateKeywordFromComponent(
      componentType,
      autoComponentState[componentType],
      "",
      "",
    );
    if (generated.error) {
      setStatus(generated.error, "error");
      return;
    }

    const targetPrice = parseInt(autoTargetPriceEl.value) || 0;
    const suggestedMinPrice = getSuggestedMinPrice(targetPrice).minPrice;
    const minInputValue = autoMinPriceEl.value.trim();
    const maxInputValue = autoMaxPriceEl.value.trim();
    const minPrice = minInputValue === "" ? suggestedMinPrice : (parseInt(minInputValue, 10) || 0);
    const maxPriceOverride = maxInputValue === "" ? null : (parseInt(maxInputValue, 10) || 0);

    if (targetPrice <= 0) {
      setStatus("Please enter a valid target price", "error");
      return;
    }

    if (currentKeywordIndex === null || currentKeywordIndex >= state.pings[selectedPingIndex].items.length) {
      setStatus("Invalid keyword index", "error");
      return;
    }

    // Update the keyword
    const ping = state.pings[selectedPingIndex];
    const kw = ping.items[currentKeywordIndex];
    const kwKeyword = ensureItemKeywordConfig(kw);
    const originalMode = autoGenerateContext.item_mode || kwKeyword.mode;
    const originalQuery = kwKeyword.query;
    const keywordMeta = getKeywordMeta(selectedPingIndex, currentKeywordIndex);
    const preserveExistingRanges = !!(
      autoGenerateContext.conversion_mode &&
      kw &&
      kw.deal_ranges &&
      typeof kw.deal_ranges === "object" &&
      typeof kw.target_price === "number" &&
      kw.target_price > 0
    );
    const ranges = preserveExistingRanges
      ? null
      : calculateDealRanges(Math.max(0, minPrice), targetPrice, componentType, maxPriceOverride);

    kwKeyword.mode = originalMode;
    if (originalMode === "query") {
      kwKeyword.query = originalQuery;
    }
    if (ranges) {
      kw.min_price = ranges.min_price;
      kw.max_price = ranges.max_price;
      kw.target_price = ranges.target_price;
      kw.deal_ranges = {
        ...ranges.deal_ranges,
        do_not_show: kw.deal_ranges?.do_not_show || [],
      };
    }

    if (componentType === "custom") {
      keywordMeta.mode = "manual";
      keywordMeta.component_type = null;
      keywordMeta.component_data = {};
    } else {
      keywordMeta.mode = "typed";
      keywordMeta.component_type = componentType;
      keywordMeta.component_data = cloneJson(autoComponentState[componentType] || {});
    }

    closeAutoGenerateModal();
    renderKeywords(ping);
    markPingChanged();
    setStatus(
      "Generated deal ranges applied.",
      "ok"
    );
  }

  function parseFirstMatch(source, pattern, fallback = "") {
    const match = String(source || "").match(pattern);
    return match && match[1] ? match[1] : fallback;
  }

  function isBlankMetaValue(value) {
    return value === null || value === undefined || String(value).trim() === "";
  }

  function reverseParseComponentData(item, componentType) {
    const itemKeyword = ensureItemKeywordConfig(item);
    const keywordText = String(itemKeyword?.filter || "");
    const friendly = String(item?.friendly_name || "");
    const combined = `${keywordText} ${friendly}`;
    const defaults = getDefaultComponentData(componentType);

    if (componentType === "nvidia_gpu") {
      defaults.brand = /GTX/i.test(combined) ? "GTX" : "RTX";
      defaults.model = parseFirstMatch(combined, /\b(\d{3,4})\b/, "");
      const friendlyLower = friendly.toLowerCase();
      const keywordLower = keywordText.toLowerCase();
      if (/ti[\s-]*super/i.test(friendlyLower) || keywordLower.includes("[\\s-]*ti[\\s-]*super\\b)")) {
        defaults.variant = "ti_super";
      } else if (/\bti\b/i.test(friendlyLower) || keywordLower.includes("[\\s-]*ti\\b(?![\\s-]*super\\b))")) {
        defaults.variant = "ti";
      } else if (/\bsuper\b/i.test(friendlyLower) || (
        keywordLower.includes("[\\s-]*super\\b)")
        && !keywordLower.includes("(?:ti|super)")
      )) {
        defaults.variant = "super";
      } else {
        defaults.variant = "normal";
      }
      defaults.vram = defaults.variant === "normal" ? parseFirstMatch(combined, /(\d{1,2})\s?GB/i, "") : "";
      return defaults;
    }

    if (componentType === "amd_gpu") {
      defaults.model = parseFirstMatch(combined, /\b(\d{4})\b/, "");
      defaults.variant = /XTX/i.test(combined) ? "xtx" : /\bXT\b/i.test(combined) ? "xt" : "normal";
      return defaults;
    }

    if (componentType === "amd_cpu") {
      defaults.ryzen = parseFirstMatch(combined, /Ryzen[\s-]*([3579])/i, defaults.ryzen);
      defaults.model = parseFirstMatch(combined, /\b(\d{4,5})\b/, "");
      defaults.suffix = parseFirstMatch(combined, /\b(X3D|X|G|T|F)\b/i, "");
      return defaults;
    }

    if (componentType === "ram") {
      defaults.capacity = parseFirstMatch(combined, /(\d{1,3})\s*GB/i, "");
      defaults.ddr = parseFirstMatch(combined, /(DDR[345])/i, defaults.ddr);
      defaults.speed = parseFirstMatch(combined, /\b(2\d{3}|3\d{3}|4\d{3}|5\d{3}|6\d{3}|7\d{3})\b/, "");
      return defaults;
    }

    if (componentType === "nvme_ssd") {
      const gb = parseFirstMatch(combined, /(\d{3,4})\s*(?:GiB|GB|G\b)/i, "");
      const tb = parseFirstMatch(combined, /(\d(?:\.\d+)?)\s*(?:TiB|TB|T\b)/i, "");
      defaults.gb = gb;
      defaults.tb = tb;
      defaults.capacity_mode = gb && tb ? "gb_tb" : (tb ? "tb" : "gb");
      return defaults;
    }

    return defaults;
  }

  function applyTypedMetaToKeyword(item, ping, keywordMeta, showError = false) {
    if (!keywordMeta || keywordMeta.mode !== "typed" || !keywordMeta.component_type) return false;
    const itemKeyword = ensureItemKeywordConfig(item);
    autoGenerateContext.item_mode = itemKeyword.mode || "poll";
    const componentType = keywordMeta.component_type;
    const componentData = (keywordMeta.component_data && typeof keywordMeta.component_data === "object")
      ? keywordMeta.component_data
      : {};
    const parsedFallbackData = reverseParseComponentData(item, componentType);
    const normalizedComponentData = {
      ...getDefaultComponentData(componentType),
      ...parsedFallbackData,
      ...componentData,
    };

    Object.keys(normalizedComponentData).forEach((key) => {
      if (isBlankMetaValue(componentData[key]) && !isBlankMetaValue(parsedFallbackData[key])) {
        normalizedComponentData[key] = parsedFallbackData[key];
      }
    });

    keywordMeta.component_data = normalizedComponentData;

    const generated = generateKeywordFromComponent(
      componentType,
      normalizedComponentData,
      itemKeyword.filter || "",
      item.friendly_name || "",
    );
    if (generated.error) {
      if (showError) {
        setStatus(generated.error, "error");
      }
      return false;
    }

    itemKeyword.filter = generated.keyword;
    item.friendly_name = generated.friendlyName;
    return true;
  }

  function renderBlocklist() {
    blocklistContainer.innerHTML = "";
    
    // Calculate diff
    const currentSet = new Set(state.blocklist);
    const originalSet = new Set(originalBlocklist);
    
    blocklistDiff = {
      added: state.blocklist.filter(item => !originalSet.has(item)),
      removed: originalBlocklist.filter(item => !currentSet.has(item))
    };
    
    state.blocklist.forEach((word, index) => {
      const row = document.createElement("div");
      row.className = "blocklist-row";
      let modeValue = isRegexBlocklistEntry(word) ? "regex" : "plain";
      const modeDropdown = createSingleSelect(
        modeValue,
        [
          { value: "plain", label: "Plaintext" },
          { value: "regex", label: "Regex" },
        ],
        (newValue) => {
          modeValue = newValue;
          const sanitizedCore = sanitizeBlocklistItem(stripRegexPrefix(input.value));
          input.value = sanitizedCore;
          state.blocklist[index] = modeValue === "regex"
            ? `regexp::${sanitizedCore}`
            : sanitizedCore;
          updateBlocklistSaveState();
          updateBlocklistDiff();
        }
      );
      modeDropdown.container.classList.add("blocklist-mode-select");
      
      const input = document.createElement("input");
      input.type = "text";
      input.value = stripRegexPrefix(word);
      input.addEventListener("input", (e) => {
        const sanitizedCore = sanitizeBlocklistItem(stripRegexPrefix(e.target.value));
        state.blocklist[index] = modeValue === "regex"
          ? `regexp::${sanitizedCore}`
          : sanitizedCore;
        updateBlocklistSaveState();
        updateBlocklistDiff();
      });
      
      const remove = document.createElement("button");
      remove.className = "danger";
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        state.blocklist.splice(index, 1);
        renderBlocklist();
        updateBlocklistSaveState();
      });
      
      row.appendChild(modeDropdown.container);
      row.appendChild(input);
      row.appendChild(remove);
      blocklistContainer.appendChild(row);
    });
    
    updateBlocklistDiffView();
  }

  function updateBlocklistDiff() {
    const currentSet = new Set(state.blocklist);
    const originalSet = new Set(originalBlocklist);
    
    blocklistDiff = {
      added: state.blocklist.filter(item => !originalSet.has(item)),
      removed: originalBlocklist.filter(item => !currentSet.has(item))
    };
    
    updateBlocklistDiffView();
  }

  function updateBlocklistDiffView() {
    const diffView = document.getElementById("blocklistDiffView");
    const diffItems = document.getElementById("blocklistDiffItems");
    const toggleBtn = document.getElementById("btnToggleBlocklistDiff");
    
    if (!diffView || !diffItems || !toggleBtn) return;
    
    const hasChanges = blocklistDiff.added.length > 0 || blocklistDiff.removed.length > 0;
    
    if (hasChanges) {
      diffView.classList.add("active");
      toggleBtn.style.display = "inline-flex";
      
      diffItems.innerHTML = "";
      
      if (blocklistDiff.removed.length > 0) {
        const header = document.createElement("div");
        header.style.cssText = "color: var(--danger); font-weight: 600; margin: 8px 0 4px 0; font-size: 0.85rem;";
        header.textContent = "Removed:";
        diffItems.appendChild(header);
        
        blocklistDiff.removed.forEach(item => {
          const div = document.createElement("div");
          div.className = "diff-item removed";
          div.innerHTML = `<span class="diff-icon">−</span><span>${escapeHtml(item)}</span>`;
          diffItems.appendChild(div);
        });
      }
      
      if (blocklistDiff.added.length > 0) {
        const header = document.createElement("div");
        header.style.cssText = "color: var(--ok); font-weight: 600; margin: 8px 0 4px 0; font-size: 0.85rem;";
        header.textContent = "Added:";
        diffItems.appendChild(header);
        
        blocklistDiff.added.forEach(item => {
          const div = document.createElement("div");
          div.className = "diff-item added";
          div.innerHTML = `<span class="diff-icon">+</span><span>${escapeHtml(item)}</span>`;
          diffItems.appendChild(div);
        });
      }
    } else {
      diffView.classList.remove("active");
      toggleBtn.style.display = "none";
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function sanitizeInput(input) {
    if (typeof input !== "string") return input;
    // Remove potentially dangerous characters and trim whitespace
    return input.trim().replace(/[<>]/g, "");
  }

  function sanitizeBlocklistItem(item) {
    if (typeof item === "string") {
      return sanitizeInput(item).toLowerCase();
    }
    return String(item || "").toLowerCase();
  }

  // Helper functions for DRY improvements
  function createButton(text, className = "", onClick = null) {
    const button = document.createElement("button");
    button.textContent = text;
    if (className) {
      button.className = className;
    }
    if (onClick) {
      button.addEventListener("click", onClick);
    }
    return button;
  }

  function createConfirmDialog(title, message, confirmLabel = "Confirm", style = "primary") {
    return confirmAction(title, message, confirmLabel, style);
  }

  function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
  }

  function renderSettings() {
    if (!settingsContainer) return;
    settingsContainer.innerHTML = "";
    
    const settingsFields = [
      { key: "discord_guild_id", label: "Primary Discord Server (Guild) ID", type: "text" },
      { key: "admin_role_id", label: "Admin Role ID", type: "text" },
      { key: "logger_webhook_ping", label: "Logger Webhook Ping Role/User ID", type: "text" },
      { key: "poll_interval_seconds", label: "Poll Interval (Seconds)", type: "number" },
      { key: "start_on_command", label: "Start on Command", type: "checkbox" },
      { key: "bot_debug_commands", label: "Enable Bot Debug Commands", type: "checkbox" },
      { key: "debug_mode", label: "Debug Mode", type: "checkbox" },
      { key: "discord_py_debug_mode", label: "Discord.py Debug Mode", type: "checkbox" },
      { key: "log_api_responses", label: "Log API Responses", type: "checkbox" },
      { key: "ping_for_warnings", label: "Ping for Scraper Warnings", type: "checkbox" },
      { key: "include_shipping_in_deal_evaluation", label: "Include Shipping in Deal Tiers", type: "checkbox" },
      { key: "include_shipping_in_price_filters", label: "Include Shipping in Price Filters", type: "checkbox" },
      { key: "file_logging", label: "Enable File Logging", type: "checkbox" },
      { key: "config_editor_host", label: "Config Editor Host", type: "text" },
      { key: "config_editor_port", label: "Config Editor Port", type: "number" },
    ];

    const grid = document.createElement("div");
    grid.className = "grid";

    settingsFields.forEach(field => {
      const wrapper = document.createElement("div");
      wrapper.className = field.type === "checkbox" ? "field checkbox-field" : "field half";
      
      const label = document.createElement("label");
      label.textContent = field.label;
      
      const input = document.createElement("input");
      input.type = field.type;
      
      if (field.type === "checkbox") {
        input.checked = !!state[field.key];
        input.addEventListener("change", () => {
          state[field.key] = input.checked;
          updateSettingsSaveState();
        });
        wrapper.appendChild(input);
        wrapper.appendChild(label);
      } else {
        input.value = state[field.key] ?? "";
        
        // Add datalist for Admin Role if possible
        if (field.key === "admin_role_id" && discordMetadata && discordMetadata.ready) {
            const listId = "list_admin_role";
            input.setAttribute("list", listId);
            const dl = document.createElement("datalist");
            dl.id = listId;
            discordMetadata.guilds.forEach(guild => {
                if (state.discord_guild_id && String(guild.id) !== String(state.discord_guild_id)) return;
                guild.roles.forEach(r => {
                    const opt = document.createElement("option");
                    opt.value = r.id;
                    opt.textContent = `${r.name} (${guild.name})`;
                    dl.appendChild(opt);
                });
            });
            document.body.appendChild(dl);
        }

        input.addEventListener("input", () => {
          if (field.type === "number") {
            state[field.key] = Number(input.value);
          } else {
            state[field.key] = input.value;
          }
          updateSettingsSaveState();
        });
        wrapper.appendChild(label);
        wrapper.appendChild(input);
      }
      grid.appendChild(wrapper);
    });

    const sleepStart = state.sleep_hours?.start ?? "";
    const sleepEnd = state.sleep_hours?.end ?? "";
    const sleepStartWrap = document.createElement("div");
    sleepStartWrap.className = "field half";
    const sleepStartLabel = document.createElement("label");
    sleepStartLabel.textContent = "Sleep Hours Start (HH:MM)";
    const sleepStartInput = document.createElement("input");
    sleepStartInput.type = "text";
    sleepStartInput.placeholder = "23:00";
    sleepStartInput.value = sleepStart;
    sleepStartInput.addEventListener("input", () => {
      if (!state.sleep_hours || typeof state.sleep_hours !== "object") {
        state.sleep_hours = { start: "", end: "" };
      }
      state.sleep_hours.start = sleepStartInput.value;
      updateSettingsSaveState();
    });
    sleepStartWrap.appendChild(sleepStartLabel);
    sleepStartWrap.appendChild(sleepStartInput);
    grid.appendChild(sleepStartWrap);

    const sleepEndWrap = document.createElement("div");
    sleepEndWrap.className = "field half";
    const sleepEndLabel = document.createElement("label");
    sleepEndLabel.textContent = "Sleep Hours End (HH:MM)";
    const sleepEndInput = document.createElement("input");
    sleepEndInput.type = "text";
    sleepEndInput.placeholder = "07:00";
    sleepEndInput.value = sleepEnd;
    sleepEndInput.addEventListener("input", () => {
      if (!state.sleep_hours || typeof state.sleep_hours !== "object") {
        state.sleep_hours = { start: "", end: "" };
      }
      state.sleep_hours.end = sleepEndInput.value;
      updateSettingsSaveState();
    });
    sleepEndWrap.appendChild(sleepEndLabel);
    sleepEndWrap.appendChild(sleepEndInput);
    grid.appendChild(sleepEndWrap);

    const arraySettings = [
      ["seller_blocklist", "Seller Blocklist", false],
      ["condition_blocklist", "Condition Blocklist", true],
    ];
    arraySettings.forEach(([key, labelText, isNumeric]) => {
      const wrapper = document.createElement("div");
      wrapper.className = "field full";
      const label = document.createElement("label");
      label.textContent = labelText;
      const trigger = document.createElement("div");
      trigger.className = "array-trigger";
      const values = Array.isArray(state[key]) ? state[key] : [];
      if (!Array.isArray(state[key])) state[key] = [];
      values.forEach((v) => {
        const chip = document.createElement("span");
        chip.className = "array-chip";
        chip.textContent = String(v);
        trigger.appendChild(chip);
      });
      trigger.addEventListener("click", () => {
        openArrayEditor(labelText, state[key] || [], !!isNumeric, (newList) => {
          state[key] = newList;
          renderSettings();
          updateSettingsSaveState();
        });
      });
      wrapper.appendChild(label);
      wrapper.appendChild(trigger);
      grid.appendChild(wrapper);
    });
    
    settingsContainer.appendChild(grid);
  }

  function renderRoleGroups() {
    if (!roleGroupsContainer) return;
    roleGroupsContainer.innerHTML = "";

    const getDiscordRoleNameById = (roleId) => {
      const target = String(roleId || "").trim();
      if (!target || !discordMetadata || !Array.isArray(discordMetadata.guilds)) return "";
      for (const guild of discordMetadata.guilds) {
        const roles = Array.isArray(guild.roles) ? guild.roles : [];
        const found = roles.find((r) => String(r.id) === target);
        if (found && found.name) {
          return String(found.name);
        }
      }
      return "";
    };

    state.self_roles.forEach((group, gIndex) => {
      const card = document.createElement("div");
      card.className = "surface nested card";
      card.style.marginBottom = "20px";
      
      const header = document.createElement("header");
      header.className = "card-head";
      
      const titleInput = document.createElement("input");
      titleInput.type = "text";
      titleInput.value = group.title || "";
      titleInput.placeholder = "Group Title (e.g. Ping Roles)";
      titleInput.style.fontWeight = "bold";
      titleInput.addEventListener("input", (e) => {
        group.title = e.target.value;
        updateRolesSaveState();
      });
      
      const actions = document.createElement("div");
      actions.className = "button-row";
      
      const addBtn = document.createElement("button");
      addBtn.className = "tonal";
      addBtn.textContent = "+ Role";
      addBtn.addEventListener("click", () => {
        if (!Array.isArray(group.roles)) group.roles = [];
        group.roles.push({ name: "", id: "" });
        renderRoleGroups();
        updateRolesSaveState();
      });
      
      const removeBtn = document.createElement("button");
      removeBtn.className = "danger";
      removeBtn.textContent = "Remove Group";
      removeBtn.addEventListener("click", async () => {
        if (await confirmAction("Remove Group", `Delete "${group.title || 'Untitled Group'}"?`, "Delete", "danger")) {
          state.self_roles.splice(gIndex, 1);
          renderRoleGroups();
          updateRolesSaveState();
        }
      });
      
      actions.appendChild(addBtn);
      actions.appendChild(removeBtn);
      header.appendChild(titleInput);
      header.appendChild(actions);
      card.appendChild(header);
      
      const rolesList = document.createElement("div");
      rolesList.className = "list-editor-container";
      rolesList.style.background = "transparent";
      rolesList.style.border = "none";
      rolesList.style.padding = "0";
           if (Array.isArray(group.roles)) {
        group.roles.forEach((role, rIndex) => {
          const normalizedRole = (role && typeof role === "object") ? role : {};
          let resolvedName = normalizedRole.name ?? normalizedRole.display_name ?? "";
          let resolvedId = normalizedRole.id ?? normalizedRole.role_id ?? normalizedRole.roleId ?? "";

          const linkedByRole = state.pings.find((p) => String(p.role) === String(resolvedId));
          if (linkedByRole) {
            if (!String(resolvedName || "").trim()) {
              resolvedName = linkedByRole.category_name || "";
            }
            if (!String(resolvedId || "").trim()) {
              resolvedId = linkedByRole.role || "";
            }
          }

          if (!String(resolvedName || "").trim() && normalizedRole.linked_ping_index != null) {
            const linkedPing = state.pings[Number(normalizedRole.linked_ping_index)];
            if (linkedPing) {
              resolvedName = linkedPing.category_name || resolvedName;
              resolvedId = linkedPing.role || resolvedId;
            }
          }

          group.roles[rIndex] = { name: String(resolvedName || ""), id: String(resolvedId || "") };
          const currentRole = group.roles[rIndex];

          const row = document.createElement("div");
          row.className = "blocklist-row role-row";

          const linkField = document.createElement("div");
          linkField.className = "role-cell role-link-cell";
          const linkLabel = document.createElement("label");
          linkLabel.textContent = "Linked Category (ping that this entry is linked to)";
          linkLabel.className = "role-cell-label";
          
          const pingSelect = document.createElement("select");
          const defaultOpt = document.createElement("option");
          defaultOpt.value = "";
          defaultOpt.textContent = "Link to Ping...";
          pingSelect.appendChild(defaultOpt);
          let selectedPingIndexByName = -1;
          let selectedPingIndexById = -1;
          
          state.pings.forEach((p, pIdx) => {
            const opt = document.createElement("option");
            opt.value = pIdx;
            const roleName = getDiscordRoleNameById(p.role);
            const pingName = p.category_name || `Ping ${pIdx + 1}`;
            opt.textContent = roleName
              ? `${pingName} (@${roleName} • ${String(p.role || "")})`
              : pingName;
            if (selectedPingIndexByName === -1 && String(pingName) === String(currentRole.name || "")) {
              selectedPingIndexByName = pIdx;
            }
            if (selectedPingIndexById === -1 && String(p.role) === String(currentRole.id)) {
              selectedPingIndexById = pIdx;
            }
            pingSelect.appendChild(opt);
          });

          if (selectedPingIndexByName >= 0) {
            pingSelect.value = String(selectedPingIndexByName);
          } else if (selectedPingIndexById >= 0) {
            pingSelect.value = String(selectedPingIndexById);
          } else {
            pingSelect.value = "";
          }
          
          pingSelect.addEventListener("change", () => {
            const selectedPing = state.pings[Number(pingSelect.value)];
            if (selectedPing) {
              currentRole.name = selectedPing.category_name || "";
              currentRole.id = String(selectedPing.role || "");
              renderRoleGroups();
              updateRolesSaveState();
            }
          });
          linkField.appendChild(linkLabel);
          linkField.appendChild(pingSelect);

          const nameField = document.createElement("div");
          nameField.className = "role-cell";
          const nameLabel = document.createElement("label");
          nameLabel.textContent = "Display Name";
          nameLabel.className = "role-cell-label";
          const nameInput = document.createElement("input");
          nameInput.type = "text";
          nameInput.value = currentRole.name || "";
          nameInput.placeholder = "Shown in Discord picker";
          nameInput.addEventListener("input", (e) => {
            currentRole.name = e.target.value;
            updateRolesSaveState();
          });
          nameField.appendChild(nameLabel);
          nameField.appendChild(nameInput);
          
          const delBtn = document.createElement("button");
          delBtn.className = "danger";
          delBtn.textContent = "×";
          delBtn.addEventListener("click", () => {
            group.roles.splice(rIndex, 1);
            renderRoleGroups();
            updateRolesSaveState();
          });
          
          row.appendChild(linkField);
          row.appendChild(nameField);
          row.appendChild(delBtn);
          rolesList.appendChild(row);
        });
      }
      
      card.appendChild(rolesList);
      roleGroupsContainer.appendChild(card);
    });
  }

  function handleMessage(message) {
    if (message.type === "state") {
      state = message.parsed || {};
      originalState = JSON.parse(JSON.stringify(state));
      state.editor_metadata = message.editor_metadata || state.editor_metadata || { version: 1, pings: [] };
      originalState.editor_metadata = cloneJson(state.editor_metadata);
      // Global blocklist is provided separately by the server.
      if (Array.isArray(message.global_blocklist)) {
        state.blocklist = [...message.global_blocklist];
        originalState.blocklist = [...message.global_blocklist];
      }
      originalBlocklist = [...(state.blocklist || [])];
      if (!Array.isArray(state.pings)) {
        state.pings = [];
      }
      if (!Array.isArray(state.blocklist)) {
        state.blocklist = [];
      }
      if (!Array.isArray(state.self_roles)) {
        state.self_roles = [];
      }
      ensureEditorMetadataForAllPings();
      if (message.discord_metadata) {
        discordMetadata = message.discord_metadata;
        
        // If the backend bot hasn't loaded guilds yet, request state again shortly (just once)
        if (discordMetadata.guilds && discordMetadata.guilds.length === 0 && !hasRetriedGuilds) {
          hasRetriedGuilds = true;
          setTimeout(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              send({ action: ACTION_GET_STATE });
            }
          }, 3000);
        }
      }
      renderSettings();
      renderBlocklist();
      renderRoleGroups();
      updateSettingsSaveState();
      updateRolesSaveState();
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }

      selectedPingIndex = Math.min(selectedPingIndex, Math.max(0, state.pings.length - 1));
      renderPingList();
      renderPingDetails();
      markPingSaved();
      setModalLoading(false); // Close modal if it was loading
      const btnDiscard = document.getElementById("btnDiscard");
      if (btnDiscard) btnDiscard.classList.remove("loading");
      setStatus(`Connected • Config Loaded`, "ok");
      
      // Handle pending ping switch after state loads
      if (window.pendingPingSwitch !== undefined) {
        performSwitch(window.pendingPingSwitch);
        delete window.pendingPingSwitch;
      }
      return;
    }

    if (message.type === "saved") {
      const keepBlocklist = state?.blocklist;
      const keepEditorMetadata = message.editor_metadata || state?.editor_metadata;
      state = message.parsed || state;
      if (Array.isArray(keepBlocklist)) {
        state.blocklist = keepBlocklist;
      }
      state.editor_metadata = keepEditorMetadata || { version: 1, pings: [] };
      ensureEditorMetadataForAllPings();
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }

      renderPingList();
      renderPingDetails();
      markPingSaved();
      setStatus(message.message || "Saved", "ok");
      return;
    }

    if (message.type === "saved_blocklist") {
      state.blocklist = Array.isArray(message.items) ? message.items : [];
      renderBlocklist();
      markPingSaved();
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }
      setStatus(message.message || "Saved global blocklist", "ok");
      return;
    }

    if (message.type === "backups") {
      renderBackupList(Array.isArray(message.items) ? message.items : []);
      setStatus("Loaded backups", "ok");
      return;
    }

    if (message.type === "restored_backup") {
      const keepBlocklist = state?.blocklist;
      const keepEditorMetadata = state?.editor_metadata;
      state = message.parsed || state;
      if (Array.isArray(keepBlocklist)) {
        state.blocklist = keepBlocklist;
      }
      state.editor_metadata = keepEditorMetadata || { version: 1, pings: [] };
      ensureEditorMetadataForAllPings();
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }

      renderPingList();
      renderPingDetails();
      markPingSaved();
      setStatus(message.message || "Restored backup", "ok");
      return;
    }

    if (message.type === "backup_deleted") {
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }
      setStatus(message.message || "Deleted backup", "ok");
      return;
    }

    if (message.type === "backup_created") {
      if (Array.isArray(message.backups)) {
        renderBackupList(message.backups);
      }
      showSuccess(message.message || "Created backup");
      return;
    }

    if (message.type === "validated") {
      setStatus(message.message || "JSON looks valid", "ok");
      return;
    }

    if (message.type === "export_json") {
      const blob = new Blob([message.content], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = message.filename || "config.json";
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus("Exported config.json", "ok");
      return;
    }

    if (message.type === "error") {
      showError(message.message || "Unknown error");
      return;
    }

    if (message.type === "validation_errors") {
      // Show which fields have errors
      showError(`Validation failed: ${message.errors.join(", ")}`);
      highlightInvalidFields(message.errors);
      return;
    }
  }

  async function loadEbayCategories() {
    if (ebayCategories.length > 0) return;
    
    try {
      const response = await fetch("/static/categories.json");
      if (response.ok) {
        const data = await response.json();
        ebayCategories = data.categories || [];
      } else {
        showError("Failed to load eBay categories");
      }
    } catch (err) {
      showError("Failed to load eBay categories");
    }
  }

  function highlightInvalidFields(errorFields) {
    // Highlight input fields that have errors
    errorFields.forEach(field => {
      const element = document.querySelector(`[data-field="${field}"]`);
      if (element) {
        element.classList.add("invalid");
        element.setAttribute("aria-invalid", "true");
      }
    });
  }

  function validatePingForSave(ping, index) {
    const errors = [];
    
    // Validate required fields
    if (!ping.category_name || !ping.category_name.trim()) {
      errors.push(`Ping ${index + 1}: Category name is required`);
    }
    
    if (!ping.channel_id || ping.channel_id === "" || ping.channel_id === 0) {
      errors.push(`Ping ${index + 1}: Channel ID is required`);
    }
    
    if (!ping.role || ping.role === "" || ping.role === 0) {
      errors.push(`Ping ${index + 1}: Role ID is required`);
    }
    
    // Validate price ranges
    ping.items.forEach((keyword, kIndex) => {
      if (keyword.min_price !== null && keyword.max_price !== null) {
        if (keyword.min_price > keyword.max_price) {
          errors.push(`Ping ${index + 1}, Item ${kIndex + 1}: Min price cannot be greater than max price`);
        }
      }
      if (keyword.target_price !== null && keyword.max_price !== null) {
        if (keyword.target_price > keyword.max_price) {
          errors.push(`Ping ${index + 1}, Item ${kIndex + 1}: Target price cannot be greater than max price`);
        }
      }
      if (keyword.target_price !== null && keyword.min_price !== null) {
        if (keyword.target_price < keyword.min_price) {
          errors.push(`Ping ${index + 1}, Item ${kIndex + 1}: Target price cannot be below min price`);
        }
      }
      
      // Validate deal ranges are in order
      if (keyword.deal_ranges) {
        const fireEnd = keyword.deal_ranges.fire_deal?.end || 0;
        const greatEnd = keyword.deal_ranges.great_deal?.end || 0;
        const goodEnd = keyword.deal_ranges.good_deal?.end || 0;
        
        if (fireEnd > greatEnd) {
          errors.push(`Ping ${index + 1}, Item ${kIndex + 1}: Fire deal end must be <= Great deal end`);
        }
        if (greatEnd > goodEnd) {
          errors.push(`Ping ${index + 1}, Item ${kIndex + 1}: Great deal end must be <= Good deal end`);
        }
      }
    });
    
    return errors;
  }

  function validateStateForSave() {
    const allErrors = [];
    
    if (!state || !state.pings) {
      return [{ field: "pings", message: "Pings array is missing" }];
    }
    
    state.pings.forEach((ping, index) => {
      const pingErrors = validatePingForSave(ping, index);
      pingErrors.forEach(error => {
        allErrors.push({ field: `ping_${index}`, message: error });
      });
    });
    
    return allErrors;
  }

  function ensurePingDefaults(ping) {
    if (!Array.isArray(ping.categories)) ping.categories = [];
    if (!Array.isArray(ping.items)) ping.items = [];
    if (!Array.isArray(ping.exclude_keywords)) ping.exclude_keywords = [];
    if (!Array.isArray(ping.blocklist_override)) ping.blocklist_override = [];
    if (!Array.isArray(ping.do_not_show)) ping.do_not_show = [];
  }

  function createDefaultPing() {
    return {
      category_name: "New Ping",
      categories: [],
      items: [],
      channel_id: 0,
      role: 0,
      price_ranges_last_updated: new Date().toISOString(),
      exclude_keywords: [],
      blocklist_override: [],
      do_not_show: [],
      is_psu: false,
    };
  }

  function createDefaultItem() {
    return {
      keyword: {
        mode: "poll",
        filter: "",
        query: null,
      },
      min_price: null,
      max_price: null,
      target_price: null,
      friendly_name: null,
      deal_ranges: {
        fire_deal: { start: 0, end: 0 },
        great_deal: { start: 0, end: 0 },
        good_deal: { start: 0, end: 0 },
        ok_deal: { start: 0, end: 0 },
        do_not_show: [],
      },
    };
  }

  function createDefaultKeywordMeta(autoFirst = false) {
    const componentType = autoFirst ? "nvidia_gpu" : null;
    return {
      mode: autoFirst ? "typed" : "manual",
      component_type: componentType,
      component_data: componentType ? getDefaultComponentData(componentType) : {},
    };
  }

  function ensureEditorMetadataForAllPings() {
    if (!state) return;
    if (!state.editor_metadata || typeof state.editor_metadata !== "object") {
      state.editor_metadata = { version: 1, pings: [] };
    }
    if (!Array.isArray(state.editor_metadata.pings)) {
      state.editor_metadata.pings = [];
    }

    state.pings.forEach((ping, pingIndex) => {
      if (!state.editor_metadata.pings[pingIndex] || typeof state.editor_metadata.pings[pingIndex] !== "object") {
        state.editor_metadata.pings[pingIndex] = { items: [] };
      }
      const pingMeta = state.editor_metadata.pings[pingIndex];
      if (!Array.isArray(pingMeta.items)) {
        pingMeta.items = [];
      }
      if (!Array.isArray(ping.items)) {
        ping.items = [];
      }

      ping.items.forEach((_item, itemIndex) => {
        const existing = pingMeta.items[itemIndex];
        if (!existing || typeof existing !== "object") {
          pingMeta.items[itemIndex] = createDefaultKeywordMeta(false);
          return;
        }
        if (existing.mode !== "manual" && existing.mode !== "typed") {
          existing.mode = "manual";
        }
        if (existing.component_type !== null && typeof existing.component_type !== "string") {
          existing.component_type = null;
        }
        if (!existing.component_data || typeof existing.component_data !== "object") {
          existing.component_data = {};
        }
      });

      pingMeta.items.length = ping.items.length;
    });

    state.editor_metadata.pings.length = state.pings.length;
  }

  function getKeywordMeta(pingIndex, keywordIndex) {
    ensureEditorMetadataForAllPings();
    const pingMeta = state.editor_metadata.pings[pingIndex];
    if (!pingMeta.items[keywordIndex]) {
      pingMeta.items[keywordIndex] = createDefaultKeywordMeta(false);
    }
    return pingMeta.items[keywordIndex];
  }

  function buildSaveParsedPayload() {
    return {
      action: ACTION_SAVE_PARSED,
      parsed: buildConfigPayloadForSave(),
      editor_metadata: state?.editor_metadata || { version: 1, pings: [] },
    };
  }

  function toNumberOrZero(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  }

  function normalizeKeywordMinMax(keyword) {
    const minValue = Math.max(0, toNumberOrZero(keyword.min_price));
    const maxValue = Math.max(minValue, toNumberOrZero(keyword.max_price));
    keyword.min_price = minValue;
    keyword.max_price = maxValue;
    return { minValue, maxValue };
  }

  function getItemPriceValidationMessage(item) {
    const min = item.min_price;
    const max = item.max_price;
    const target = item.target_price;

    if (min !== null && max !== null && min > max) {
      return "Min price cannot be greater than max price.";
    }
    if (target !== null && max !== null && target > max) {
      return "Target price cannot be greater than max price.";
    }
    if (target !== null && min !== null && target < min) {
      return "Target price cannot be below min price.";
    }
    return null;
  }

  function validateKeywordPrices(keyword) {
    // Ensure min_price <= max_price
    if (typeof keyword.min_price === "number" && typeof keyword.max_price === "number") {
      if (keyword.min_price > keyword.max_price) {
        keyword.max_price = keyword.min_price;
      }
    }

    // Ensure deal range thresholds are in order
    if (keyword.deal_ranges) {
      const fireEnd = toNumberOrZero(keyword.deal_ranges.fire_deal?.end);
      const greatEnd = toNumberOrZero(keyword.deal_ranges.great_deal?.end);
      const goodEnd = toNumberOrZero(keyword.deal_ranges.good_deal?.end);
      const max = keyword.max_price ?? 0;

      // Normalize thresholds to be within [min, max] and in order
      const min = keyword.min_price ?? 0;
      const sorted = [fireEnd, greatEnd, goodEnd].sort((a, b) => a - b);

      keyword.deal_ranges.fire_deal.end = Math.max(min, Math.min(max, sorted[0]));
      keyword.deal_ranges.great_deal.end = Math.max(min, Math.min(max, sorted[1]));
      keyword.deal_ranges.good_deal.end = Math.max(min, Math.min(max, sorted[2]));
    }
  }

  function createUnifiedTierEditor(keyword, ping) {
    const editor = document.createElement("div");
    editor.className = "field full tier-editor";

    const label = document.createElement("label");
    label.textContent = "Deal Ranges";
    editor.appendChild(label);

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "Drag handles to set deal ranges.";
    editor.appendChild(hint);

    if (!keyword.deal_ranges || typeof keyword.deal_ranges !== "object") {
      keyword.deal_ranges = createDefaultItem().deal_ranges;
    }

    dealNames.forEach((dealName) => {
      if (!keyword.deal_ranges[dealName]) {
        keyword.deal_ranges[dealName] = { start: 0, end: 0 };
      }
    });

    const { minValue, maxValue } = normalizeKeywordMinMax(keyword);

    const fireEndValue = toNumberOrZero(keyword.deal_ranges.fire_deal?.end);
    const greatEndValue = toNumberOrZero(keyword.deal_ranges.great_deal?.end);
    const goodEndValue = toNumberOrZero(keyword.deal_ranges.good_deal?.end);

    const thresholds = [
      Math.max(minValue, Math.min(maxValue, fireEndValue)),
      Math.max(minValue, Math.min(maxValue, greatEndValue)),
      Math.max(minValue, Math.min(maxValue, goodEndValue)),
    ];

    const track = document.createElement("div");
    track.className = "tier-track";

    const markerDefs = [
      { key: "min", label: "Min", cls: "min" },
      { key: "fire", label: "Fire", cls: "fire" },
      { key: "great", label: "Great", cls: "great" },
      { key: "good", label: "Good", cls: "good" },
      { key: "max", label: "Max", cls: "max" },
    ];

    const markerEls = [];
    markerDefs.forEach((markerDef) => {
      const marker = document.createElement("div");
      marker.className = `tier-marker ${markerDef.cls}`;
      // Add value span for displaying actual price
      marker.innerHTML = `<span class="tier-icon">${markerDef.label.charAt(0)}</span><span class="tier-label">${markerDef.label}</span><span class="tier-value">$0</span>`;
      track.appendChild(marker);
      markerEls.push(marker);
    });

    const sliderInputs = [];
    const sliderMarkerDefs = markerDefs.slice(1, 4);
    sliderMarkerDefs.forEach((markerDef, index) => {
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0";
      slider.max = "1000";
      slider.step = "1";
      slider.className = `tier-handle ${markerDef.cls}`;
      slider.dataset.index = String(index);
      track.appendChild(slider);
      sliderInputs.push(slider);
    });

    const numberRow = document.createElement("div");
    numberRow.className = "tier-numbers";

    const numberInputs = [];
    sliderMarkerDefs.forEach((markerDef, index) => {
      const numberWrap = document.createElement("div");
      numberWrap.className = "tier-number-wrap";

      const numberLabel = document.createElement("label");
      numberLabel.className = "tier-number-label";
      numberLabel.innerHTML = `<span class="tier-icon ${markerDef.cls}">${markerDef.label.charAt(0)}</span>${markerDef.label}`;

      const numberInput = document.createElement("input");
      numberInput.type = "number";
      numberInput.min = String(minValue);
      numberInput.max = String(maxValue);
      numberInput.step = "1";
      numberInput.dataset.index = String(index);
      numberInput.className = "range-input";

      numberWrap.appendChild(numberLabel);
      numberWrap.appendChild(numberInput);
      numberRow.appendChild(numberWrap);
      numberInputs.push(numberInput);
    });

    function normalizeThresholds(changedIndex) {
      for (let i = changedIndex - 1; i >= 0; i -= 1) {
        thresholds[i] = Math.min(thresholds[i], thresholds[i + 1]);
      }
      for (let i = changedIndex + 1; i < thresholds.length; i += 1) {
        thresholds[i] = Math.max(thresholds[i], thresholds[i - 1]);
      }

      for (let i = 0; i < thresholds.length; i += 1) {
        thresholds[i] = Math.max(minValue, Math.min(maxValue, Math.round(thresholds[i])));
      }
    }

    function nextTierStart(prevEnd, thisEnd) {
      const candidate = prevEnd + 1;
      return candidate <= thisEnd ? candidate : thisEnd;
    }

    function applyToKeyword() {
      const [fireEnd, greatEnd, goodEnd] = thresholds;
      keyword.min_price = minValue;
      keyword.max_price = maxValue;

      keyword.deal_ranges.fire_deal.start = minValue;
      keyword.deal_ranges.fire_deal.end = fireEnd;

      keyword.deal_ranges.great_deal.start = nextTierStart(fireEnd, greatEnd);
      keyword.deal_ranges.great_deal.end = greatEnd;

      keyword.deal_ranges.good_deal.start = nextTierStart(greatEnd, goodEnd);
      keyword.deal_ranges.good_deal.end = goodEnd;

      keyword.deal_ranges.ok_deal.start = nextTierStart(goodEnd, maxValue);
      keyword.deal_ranges.ok_deal.end = maxValue;

      if (typeof keyword.target_price === "number") {
        keyword.target_price = Math.max(minValue, Math.min(maxValue, keyword.target_price));
      }
    }

    // Use piecewise linear scaling for better distribution across all price ranges
    // This gives more visual space to HIGHER tiers where the deals are
    const range = maxValue - minValue;
    
    function pctFromValue(value) {
      if (maxValue <= minValue) {
        return value <= minValue ? 0 : 100;
      }
      
      const normalized = (value - minValue) / range;
      
      // Piecewise linear: give MORE space to higher tiers (where deals are)
      // Bottom 30% of price range gets only 10% of visual space
      // Next 30% gets 15% of visual space
      // Next 20% gets 25% of visual space
      // Top 20% gets 50% of visual space (where the good deals are!)
      if (normalized < 0.3) {
        return normalized * (10 / 0.3);
      } else if (normalized < 0.6) {
        return 10 + (normalized - 0.3) * (15 / 0.3);
      } else if (normalized < 0.8) {
        return 25 + (normalized - 0.6) * (25 / 0.2);
      } else {
        return 50 + (normalized - 0.8) * (50 / 0.2);
      }
    }

    function valueFromPct(pct) {
      // Reverse the piecewise linear mapping
      let normalized;
      if (pct < 10) {
        normalized = (pct / 10) * 0.3;
      } else if (pct < 25) {
        normalized = 0.3 + ((pct - 10) / 15) * 0.3;
      } else if (pct < 50) {
        normalized = 0.6 + ((pct - 25) / 25) * 0.2;
      } else {
        normalized = 0.8 + ((pct - 50) / 50) * 0.2;
      }
      
      return Math.round(minValue + range * normalized);
    }

    function syncUi(markDirty = true) {
      sliderInputs.forEach((slider, index) => {
        slider.value = String(pctFromValue(thresholds[index]) * 10);
      });

      numberInputs.forEach((input, index) => {
        input.value = String(thresholds[index]);
      });

      const pct = [
        pctFromValue(minValue),
        pctFromValue(thresholds[0]),
        pctFromValue(thresholds[1]),
        pctFromValue(thresholds[2]),
        pctFromValue(maxValue),
      ];
      track.style.setProperty("--p0", `${pct[0]}%`);
      track.style.setProperty("--p1", `${pct[1]}%`);
      track.style.setProperty("--p2", `${pct[2]}%`);
      track.style.setProperty("--p3", `${pct[3]}%`);
      track.style.setProperty("--p4", `${pct[4]}%`);

      const valuesToShow = [minValue, thresholds[0], thresholds[1], thresholds[2], maxValue];
      markerEls.forEach((marker, index) => {
        marker.style.left = `${pct[index]}%`;
        // Update marker to show actual price value
        const valueSpan = marker.querySelector(".tier-value");
        if (valueSpan) {
          valueSpan.textContent = `$${valuesToShow[index]}`;
        }
      });

      applyToKeyword();

      if (markDirty) {
        markPingChanged();
      }
    }

    sliderInputs.forEach((slider, index) => {
      slider.addEventListener("change", () => {
        thresholds[index] = valueFromPct(Number(slider.value) / 10);
        normalizeThresholds(index);
        syncUi();
      });
    });

    numberInputs.forEach((input, index) => {
      input.addEventListener("change", () => {
        thresholds[index] = Number(input.value || minValue);
        normalizeThresholds(index);
        syncUi();
      });
    });

    normalizeThresholds(thresholds.length - 1);
    syncUi(false);

    editor.appendChild(track);
    editor.appendChild(numberRow);
    return editor;
  }

  function createMultiSelect(selectedValues, options, onChange, placeholder) {
    const container = document.createElement("div");
    container.className = "custom-select";

    const trigger = document.createElement("div");
    trigger.className = "select-trigger";
    
    const updateLabel = () => {
      if (!selectedValues || selectedValues.length === 0) {
        trigger.textContent = placeholder;
      } else {
        trigger.textContent = selectedValues.map(v => toTitleCase(v.replace("_", " "))).join(", ");
      }
    };
    updateLabel();

    const menu = document.createElement("div");
    menu.className = "select-menu";

    options.forEach(option => {
      const item = document.createElement("label");
      item.className = "checkbox-item";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selectedValues.includes(option);
      cb.addEventListener("change", () => {
        if (cb.checked) {
          if (!selectedValues.includes(option)) selectedValues.push(option);
        } else {
          const index = selectedValues.indexOf(option);
          if (index > -1) selectedValues.splice(index, 1);
        }
        updateLabel();
        onChange([...selectedValues]);
      });
      item.appendChild(cb);
      item.appendChild(document.createTextNode((" " + toTitleCase(option.replace("_", " ")))));
      menu.appendChild(item);
    });

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = menu.classList.contains("open");
      // Close all other menus first
      document.querySelectorAll(".select-menu").forEach(m => m.classList.remove("open"));
      if (!isOpen) menu.classList.add("open");
    });

    document.addEventListener("click", () => {
      menu.classList.remove("open");
    });

    menu.addEventListener("click", (e) => {
      e.stopPropagation();
    });

    container.appendChild(trigger);
    container.appendChild(menu);
    return container;
  }

  function renderPingList() {
    pingListEl.innerHTML = "";
    state.pings.forEach((ping, index) => {
      ensurePingDefaults(ping);
      const button = document.createElement("button");
      button.className = `ping-item ${index === selectedPingIndex ? "active" : ""}`;
      button.textContent = `${index + 1}. ${ping.category_name || "Untitled Ping"}`;
      button.addEventListener("click", () => {
        handlePingSwitch(index);
      });
      pingListEl.appendChild(button);
    });
  }

  const unsavedChangesOverlayEl = document.getElementById("unsavedChangesOverlay");
  let switchTargetIndex = null;

  async function handlePingSwitch(index) {
    if (index === selectedPingIndex) return;
    
    if (hasPendingPingChanges) {
      switchTargetIndex = index;
      const currentPing = state.pings[selectedPingIndex];
      document.getElementById("unsavedChangesTitle").textContent = `Unsaved: ${currentPing.category_name || "Untitled"}`;
      unsavedChangesOverlayEl.classList.add("open");
      unsavedChangesOverlayEl.setAttribute("aria-hidden", "false");
    } else {
      performSwitch(index);
    }
  }

  function performSwitch(index) {
    selectedPingIndex = index;
    renderPingList();
    renderPingDetails();
    markPingSaved(); // Reset state tracking for the new ping
  }

  function closeSwitchModal() {
    unsavedChangesOverlayEl.classList.remove("open");
    unsavedChangesOverlayEl.setAttribute("aria-hidden", "true");
    switchTargetIndex = null;
  }

  function renderBackupList(items) {
    backups = items;
    backupListEl.innerHTML = "";

    if (!backups.length) {
      const option = document.createElement("option");
      option.textContent = "No backups found";
      option.disabled = true;
      backupListEl.appendChild(option);
      backupMetaEl.textContent = "No backup selected.";
      return;
    }

    backups.forEach((backup) => {
      const option = document.createElement("option");
      option.value = backup.name;
      option.textContent = `${backup.name} (${backup.kind})`;
      backupListEl.appendChild(option);
    });

    backupListEl.selectedIndex = 0;
    updateBackupMeta();
  }

  function updateBackupMeta() {
    const selectedName = backupListEl.value;
    const selected = backups.find((backup) => backup.name === selectedName);
    if (!selected) {
      backupMetaEl.textContent = "No backup selected.";
      return;
    }

    backupMetaEl.textContent = `Kind: ${selected.kind} | Updated: ${selected.modified} | Size: ${formatBytes(selected.size)}`;
  }

  function createFieldWithTooltip(labelText, type, cls, tooltipText, fieldName = "") {
    const wrapper = document.createElement("div");
    wrapper.className = `field ${cls}`;
    
    const labelRow = document.createElement("div");
    labelRow.style.display = "flex";
    labelRow.style.alignItems = "center";
    labelRow.style.gap = "6px";
    
    const label = document.createElement("label");
    label.textContent = labelText;
    labelRow.appendChild(label);
    
    if (tooltipText) {
      const tooltipContainer = document.createElement("div");
      tooltipContainer.className = "tooltip-container";
      
      const tooltipIcon = document.createElement("span");
      tooltipIcon.className = "tooltip-icon";
      tooltipIcon.textContent = "ⓘ";
      tooltipIcon.setAttribute("aria-label", "Help");
      
      const tooltipTextEl = document.createElement("span");
      tooltipTextEl.className = "tooltip-text";
      tooltipTextEl.textContent = tooltipText;
      
      tooltipContainer.appendChild(tooltipIcon);
      tooltipContainer.appendChild(tooltipTextEl);
      labelRow.appendChild(tooltipContainer);
    }
    
    wrapper.appendChild(labelRow);
    
    const input = document.createElement("input");
    input.type = type;
    if (fieldName) {
      input.dataset.field = fieldName;
    }
    
    wrapper.appendChild(input);
    return wrapper;
  }

  function renderPingDetails() {
    pingFormEl.innerHTML = "";
    keywordCardsEl.innerHTML = "";

    if (!state || !state.pings || state.pings.length === 0) {
      pingFormEl.innerHTML = '<div class="muted">No ping configs. Add one from the sidebar.</div>';
      updatePingSaveButtonState();
      return;
    }

    const ping = state.pings[selectedPingIndex];
    ensurePingDefaults(ping);
    ensureEditorMetadataForAllPings();

    const fields = [
      ["category_name", "Category Name", "text", "full", "The display name for this ping category"],
      ["channel_id", "Channel", "text", "half", "The Discord channel where listings will be sent"],
      ["role", "Role", "text", "half", "The Discord role that will be pinged when deals are found"],
    ];

    fields.forEach(([key, labelText, type, cls, tooltipText]) => {
      if (key === "channel_id" || key === "role") {
        // Special handling for channel/role with custom dropdown
        const wrapper = document.createElement("div");
        wrapper.className = `field ${cls}`;
        
        const labelRow = document.createElement("div");
        labelRow.style.display = "flex";
        labelRow.style.alignItems = "center";
        labelRow.style.gap = "6px";
        
        const label = document.createElement("label");
        label.textContent = labelText;
        labelRow.appendChild(label);
        
        if (tooltipText) {
          const tooltipContainer = document.createElement("div");
          tooltipContainer.className = "tooltip-container";
          
          const tooltipIcon = document.createElement("span");
          tooltipIcon.className = "tooltip-icon";
          tooltipIcon.textContent = "ⓘ";
          tooltipIcon.setAttribute("aria-label", "Help");
          
          const tooltipTextEl = document.createElement("span");
          tooltipTextEl.className = "tooltip-text";
          tooltipTextEl.textContent = tooltipText;
          
          tooltipContainer.appendChild(tooltipIcon);
          tooltipContainer.appendChild(tooltipTextEl);
          labelRow.appendChild(tooltipContainer);
        }
        
        wrapper.appendChild(labelRow);
        
        if (discordMetadata && discordMetadata.ready) {
          const selectWrapper = document.createElement("div");
          selectWrapper.className = "custom-select";
          
          const trigger = document.createElement("div");
          trigger.className = "select-trigger";
          
          const menu = document.createElement("div");
          menu.className = "select-menu";
          menu.style.maxHeight = "300px";
          menu.style.overflowY = "auto";
          menu.style.zIndex = "100";
          
          // Add search input
          const searchInput = document.createElement("input");
          searchInput.type = "text";
          searchInput.placeholder = `Search ${key === "channel_id" ? "channels" : "roles"}...`;
          searchInput.className = "select-search-input";
          searchInput.style.marginBottom = "8px";
          searchInput.style.width = "100%";
          searchInput.style.boxSizing = "border-box";
          menu.appendChild(searchInput);
          
          let selectedItem = null;
          let count = 0;
          let allItems = [];
          
          discordMetadata.guilds.forEach(guild => {
            // Filter by primary guild if set
            if (state.discord_guild_id && String(guild.id) !== String(state.discord_guild_id)) {
              return;
            }
            
            const items = key === "channel_id" ? guild.channels : guild.roles;
            items.forEach(item => {
              count++;
              allItems.push(item);
            });
          });
          
          const filterItems = (searchTerm) => {
            const term = searchTerm.toLowerCase().trim();
            menu.querySelectorAll(".channel-role-item").forEach(item => {
              const name = item.dataset.name.toLowerCase();
              const id = item.dataset.id;
              const show = !term || name.includes(term) || id.includes(term);
              item.style.display = show ? "flex" : "none";
            });
          };
          
          searchInput.addEventListener("input", (e) => {
            filterItems(e.target.value);
          });
          
          allItems.forEach(item => {
            const opt = document.createElement("div");
            opt.className = "channel-role-item";
            opt.style.display = "flex";
            opt.style.flexDirection = "column";
            opt.style.alignItems = "flex-start";
            opt.style.padding = "6px 8px";
            opt.style.borderRadius = "6px";
            opt.style.cursor = "pointer";
            opt.style.transition = "background 0.1s";
            opt.dataset.name = item.name;
            opt.dataset.id = item.id;
            
            const titleText = key === "channel_id" ? `#${item.name}` : `@${item.name}`;
            
            const title = document.createElement("span");
            title.textContent = titleText;
            title.style.fontWeight = "500";
            title.style.fontSize = "0.88rem";
            
            const subtext = document.createElement("span");
            subtext.textContent = item.id;
            subtext.style.fontSize = "0.75rem";
            subtext.style.opacity = "0.7";
            subtext.style.fontFamily = "monospace";
            
            opt.appendChild(title);
            opt.appendChild(subtext);
            
            if (String(ping[key]) === String(item.id)) {
              selectedItem = { title: titleText, id: item.id };
            }
            
            opt.addEventListener("click", (e) => {
              e.stopPropagation();
              ping[key] = item.id;
              trigger.innerHTML = `${titleText} <span style="opacity: 0.5; font-size: 0.7em; margin-left: 6px;">▼</span>`;
              menu.classList.remove("open");
              searchInput.value = "";
              markPingChanged();
            });
            
            opt.addEventListener("mouseenter", () => {
              opt.style.background = "var(--surface-muted)";
            });
            
            opt.addEventListener("mouseleave", () => {
              opt.style.background = "transparent";
            });
            
            menu.appendChild(opt);
          });
          
          if (count === 0) {
            trigger.innerHTML = `No ${key}s found <span style="opacity: 0.5; font-size: 0.7em; margin-left: 6px;">▼</span>`;
            trigger.style.opacity = "0.5";
            trigger.style.pointerEvents = "none";
          } else if (selectedItem) {
            trigger.innerHTML = `${selectedItem.title} <span style="opacity: 0.5; font-size: 0.7em; margin-left: 6px;">▼</span>`;
          } else {
            trigger.innerHTML = `Select a ${key === "channel_id" ? "channel" : key}... <span style="opacity: 0.5; font-size: 0.7em; margin-left: 6px;">▼</span>`;
          }
          
          trigger.addEventListener("click", (e) => {
            e.stopPropagation();
            document.querySelectorAll(".select-menu").forEach(m => {
              if (m !== menu) m.classList.remove("open");
            });
            menu.classList.toggle("open");
            if (menu.classList.contains("open")) {
              searchInput.focus();
            }
          });
          
          selectWrapper.appendChild(trigger);
          selectWrapper.appendChild(menu);
          wrapper.appendChild(selectWrapper);
          pingFormEl.appendChild(wrapper);
          return; // Skip the standard input appending below
        } else {
          // Fallback to regular input if Discord metadata not ready
          const input = document.createElement("input");
          input.type = type;
          input.placeholder = "Paste ID here...";
          input.addEventListener("change", () => {
            ping[key] = input.value;
            markPingChanged();
          });
          wrapper.appendChild(input);
          pingFormEl.appendChild(wrapper);
          return;
        }
      }
      
      // Standard field handling for other fields
      const wrapper = createFieldWithTooltip(labelText, type, cls, tooltipText, key);
      const input = wrapper.querySelector("input");

      input.value = ping[key] ?? "";
      input.addEventListener("change", () => {
        ping[key] = input.value;
        markPingChanged();
      });
      pingFormEl.appendChild(wrapper);
    });

    const arrayFields = [
      ["categories", "Categories", true, "Categories to poll from when searching for deals"],
      ["exclude_keywords", "Exclude Keywords", false, "Keywords that will prevent pings from being sent"],
      ["blocklist_override", "Blocklist Override", false, "Keywords to allow even if they are in the global blocklist"],
    ];

    arrayFields.forEach(([key, labelText, isNumeric, tooltipText]) => {
      const wrapper = document.createElement("div");
      wrapper.className = "field half";
      
      const labelRow = document.createElement("div");
      labelRow.style.display = "flex";
      labelRow.style.alignItems = "center";
      labelRow.style.gap = "6px";
      
      const label = document.createElement("label");
      label.textContent = labelText;
      labelRow.appendChild(label);
      
      if (tooltipText) {
        const tooltipContainer = document.createElement("div");
        tooltipContainer.className = "tooltip-container";
        
        const tooltipIcon = document.createElement("span");
        tooltipIcon.className = "tooltip-icon";
        tooltipIcon.textContent = "ⓘ";
        tooltipIcon.setAttribute("aria-label", "Help");
        
        const tooltipTextEl = document.createElement("span");
        tooltipTextEl.className = "tooltip-text";
        tooltipTextEl.textContent = tooltipText;
        
        tooltipContainer.appendChild(tooltipIcon);
        tooltipContainer.appendChild(tooltipTextEl);
        labelRow.appendChild(tooltipContainer);
      }
      
      wrapper.appendChild(labelRow);
      
      const trigger = document.createElement("div");
      trigger.className = "array-trigger";
      const updateTrigger = () => {
        trigger.innerHTML = "";
        (ping[key] || []).forEach(val => {
          const chip = document.createElement("span");
          chip.className = "array-chip";
          chip.textContent = val;
          trigger.appendChild(chip);
        });
      };
      updateTrigger();
      
      // Special handling for categories - use searchable selector
      if (key === "categories") {
        trigger.addEventListener("click", () => {
          openCategorySelector(ping[key] || [], (newList) => {
            ping[key] = newList;
            updateTrigger();
            markPingChanged();
          });
        });
      } else {
        // Use array editor for other fields
        trigger.addEventListener("click", () => {
          openArrayEditor(labelText, ping[key] || [], isNumeric, (newList) => {
            ping[key] = newList;
            updateTrigger();
            markPingChanged();
          });
        });
      }
      
      wrapper.appendChild(trigger);
      pingFormEl.appendChild(wrapper);
    });

    const pingDnsWrap = document.createElement("div");
    pingDnsWrap.className = "field full";
    
    const pingDnsLabelRow = document.createElement("div");
    pingDnsLabelRow.style.display = "flex";
    pingDnsLabelRow.style.alignItems = "center";
    pingDnsLabelRow.style.gap = "6px";
    
    const pingDnsLabel = document.createElement("label");
    pingDnsLabel.textContent = "Ping-level Do Not Show (Excludes all deals in the selected tiers in this ping only)";
    pingDnsLabelRow.appendChild(pingDnsLabel);
    
    const pingDnsTooltip = document.createElement("div");
    pingDnsTooltip.className = "tooltip-container";
    const pingDnsTooltipIcon = document.createElement("span");
    pingDnsTooltipIcon.className = "tooltip-icon";
    pingDnsTooltipIcon.textContent = "ⓘ";
    const pingDnsTooltipText = document.createElement("span");
    pingDnsTooltipText.className = "tooltip-text";
    pingDnsTooltipText.textContent = "Select deal tiers (fire_deal, great_deal, etc.) that should not trigger pings for this specific ping only.";
    pingDnsTooltip.appendChild(pingDnsTooltipIcon);
    pingDnsTooltip.appendChild(pingDnsTooltipText);
    pingDnsLabelRow.appendChild(pingDnsTooltip);
    
    pingDnsWrap.appendChild(pingDnsLabelRow);

    const pingDnsSelect = createMultiSelect(
      ping.do_not_show || [],
      dealNames,
      (newValues) => {
        ping.do_not_show = newValues;
        markPingChanged();
      },
      "Select tiers to exclude..."
    );
    pingDnsWrap.appendChild(pingDnsSelect);
    pingFormEl.appendChild(pingDnsWrap);

    const isPsuWrap = document.createElement("div");
    isPsuWrap.className = "field half checkbox-field";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.id = "is_psu_cb";
    cb.checked = !!ping.is_psu;
    cb.addEventListener("change", () => {
      ping.is_psu = cb.checked;
      markPingChanged();
    });
    const cbLabel = document.createElement("label");
    cbLabel.setAttribute("for", "is_psu_cb");
    cbLabel.textContent = "Is this a PSU-specific ping? (Enables SPL's PSU Tierlist integration)";
    isPsuWrap.appendChild(cb);
    isPsuWrap.appendChild(cbLabel);
    pingFormEl.appendChild(isPsuWrap);

    renderKeywords(ping);
    updatePingSaveButtonState();
  }

  function renderKeywords(ping) {
    keywordCardsEl.innerHTML = "";
    ensureEditorMetadataForAllPings();

    ping.items.forEach((item, keywordIndex) => {
      const itemKeyword = ensureItemKeywordConfig(item);
      if (!item.deal_ranges) {
        item.deal_ranges = createDefaultItem().deal_ranges;
      }
      const keywordMeta = getKeywordMeta(selectedPingIndex, keywordIndex);
      const card = document.createElement("div");
      card.className = "surface nested card small";
      const itemValidationMessage = getItemPriceValidationMessage(item);
      if (itemValidationMessage) {
        const banner = document.createElement("div");
        banner.className = "validation-banner";
        banner.textContent = `Validation error: ${itemValidationMessage}`;
        card.appendChild(banner);
      }

      const head = document.createElement("div");
      head.className = "card-head";
      const title = document.createElement("h2");
      title.textContent = `Item ${keywordIndex + 1}`;

      const workflowControls = document.createElement("div");
      workflowControls.className = "keyword-quick-adjust";

      const operationModeSelect = document.createElement("select");
      const pollModeOpt = document.createElement("option");
      pollModeOpt.value = "poll";
      pollModeOpt.textContent = "Poll";
      const queryModeOpt = document.createElement("option");
      queryModeOpt.value = "query";
      queryModeOpt.textContent = "Query";
      operationModeSelect.appendChild(pollModeOpt);
      operationModeSelect.appendChild(queryModeOpt);
      operationModeSelect.value = itemKeyword.mode || "poll";
      operationModeSelect.addEventListener("change", () => {
        itemKeyword.mode = operationModeSelect.value;
        if (itemKeyword.mode === "poll") {
          itemKeyword.query = null;
          if (typeof itemKeyword.filter !== "string") itemKeyword.filter = "";
        }
        renderKeywords(ping);
        markPingChanged();
      });

      const duplicateKeywordButton = document.createElement("button");
      duplicateKeywordButton.className = "tonal";
      duplicateKeywordButton.textContent = "Duplicate";
      duplicateKeywordButton.addEventListener("click", () => {
        const copy = JSON.parse(JSON.stringify(item));
        ping.items.splice(keywordIndex + 1, 0, copy);
        const copiedMeta = cloneJson(keywordMeta || createDefaultKeywordMeta(false));
        state.editor_metadata.pings[selectedPingIndex].items.splice(keywordIndex + 1, 0, copiedMeta);
        renderKeywords(ping);
        markPingChanged();
        setStatus(`Duplicated item ${keywordIndex + 1}.`, "ok");
      });

      const removeButton = document.createElement("button");
      removeButton.className = "danger";
      removeButton.textContent = "Remove";
      removeButton.addEventListener("click", async () => {
        const shouldDelete = await confirmAction(
          "Delete Item",
          `Delete item ${keywordIndex + 1}?`,
          "Delete",
          "danger"
        );
        if (!shouldDelete) return;
        ping.items.splice(keywordIndex, 1);
        state.editor_metadata.pings[selectedPingIndex].items.splice(keywordIndex, 1);
        renderKeywords(ping);
        markPingChanged();
      });
      workflowControls.appendChild(operationModeSelect);
      head.appendChild(title);
      head.appendChild(workflowControls);
      head.appendChild(duplicateKeywordButton);
      head.appendChild(removeButton);

      const grid = document.createElement("div");
      grid.className = "grid";

      const addLabelWithTooltip = (labelEl, tooltipText) => {
        if (!tooltipText) return labelEl;
        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.alignItems = "center";
        row.style.gap = "6px";
        row.appendChild(labelEl);

        const tooltip = document.createElement("div");
        tooltip.className = "tooltip-container";
        const icon = document.createElement("span");
        icon.className = "tooltip-icon";
        icon.textContent = "ⓘ";
        const text = document.createElement("span");
        text.className = "tooltip-text";
        text.textContent = tooltipText;
        tooltip.appendChild(icon);
        tooltip.appendChild(text);
        row.appendChild(tooltip);
        return row;
      };

      const addKeywordSectionHeader = (titleText, tooltipText = "") => {
        const section = document.createElement("div");
        section.className = "field full";
        const heading = document.createElement("label");
        heading.style.fontWeight = "600";
        heading.style.letterSpacing = "0";
        heading.textContent = titleText;
        section.appendChild(addLabelWithTooltip(heading, tooltipText));
        grid.appendChild(section);
      };

      const isTyped = keywordMeta.mode === "typed" && !!keywordMeta.component_type;
      if (isTyped) {
        addKeywordSectionHeader("Component");
        const componentType = keywordMeta.component_type;
        if (!keywordMeta.component_data || typeof keywordMeta.component_data !== "object") {
          keywordMeta.component_data = getDefaultComponentData(componentType);
        }
        const componentData = keywordMeta.component_data;

        const addTypedField = (key, labelText, type = "text", cls = "half", options = null, placeholder = "") => {
          const wrapper = document.createElement("div");
          wrapper.className = `field ${cls}`;
          const label = document.createElement("label");
          label.textContent = labelText;
          wrapper.appendChild(label);

          let input;
          if (type === "select") {
            input = document.createElement("select");
            options.forEach((option) => {
              const optionEl = document.createElement("option");
              if (typeof option === "string") {
                optionEl.value = option;
                optionEl.textContent = option;
              } else {
                optionEl.value = option.value;
                optionEl.textContent = option.label;
              }
              input.appendChild(optionEl);
            });
          } else {
            input = document.createElement("input");
            input.type = type;
            if (placeholder) input.placeholder = placeholder;
          }
          input.value = componentData[key] ?? "";
          input.addEventListener("change", () => {
            componentData[key] = input.value;
            if (!applyTypedMetaToKeyword(item, ping, keywordMeta, true)) {
              setStatus("Missing required typed fields. Update the missing values to continue.", "warning");
            } else {
              renderKeywords(ping);
              markPingChanged();
            }
          });

          wrapper.appendChild(input);
          grid.appendChild(wrapper);
        };

        if (componentType === "nvidia_gpu") {
          addTypedField("brand", "GPU Brand", "select", "third", ["RTX", "GTX"]);
          addTypedField("model", "Model", "text", "third", null, "e.g., 5070");
          addTypedField("variant", "Variant", "select", "third", [
            { value: "normal", label: "Normal" },
            { value: "ti", label: "Ti" },
            { value: "super", label: "SUPER" },
            { value: "ti_super", label: "Ti SUPER" },
          ]);
          if (componentData.variant === "normal") {
            addTypedField("vram", "VRAM (Optional)", "number", "third", null, "e.g., 12");
          }
        } else if (componentType === "amd_gpu") {
          addTypedField("model", "Model", "text", "half", null, "e.g., 9070");
          addTypedField("variant", "Variant", "select", "half", [
            { value: "normal", label: "Normal" },
            { value: "xt", label: "XT" },
            { value: "xtx", label: "XTX" },
          ]);
        } else if (componentType === "amd_cpu") {
          addTypedField("ryzen", "Ryzen Series", "select", "third", ["3", "5", "7", "9"]);
          addTypedField("model", "Model", "text", "third", null, "e.g., 7800");
          addTypedField("suffix", "Suffix (Optional)", "text", "third", null, "e.g., X3D");
        } else if (componentType === "ram") {
          addTypedField("capacity", "Capacity (GB)", "number", "third");
          addTypedField("ddr", "DDR Type", "text", "third", null, "DDR5");
          addTypedField("speed", "Speed (MHz)", "number", "third");
        } else if (componentType === "nvme_ssd") {
          addTypedField("capacity_mode", "Capacity Mode", "select", "third", [
            { value: "gb", label: "GB only" },
            { value: "tb", label: "TB only" },
            { value: "gb_tb", label: "GB or TB" },
          ]);
          if (componentData.capacity_mode === "gb" || componentData.capacity_mode === "gb_tb") {
            addTypedField("gb", "GB Value / Regex", "text", "third", null, "e.g., 512");
          }
          if (componentData.capacity_mode === "tb" || componentData.capacity_mode === "gb_tb") {
            addTypedField("tb", "TB Value / Regex", "text", "third", null, "e.g., 1");
          }
        }

        addKeywordSectionHeader(
          "Matching",
          "Filter supports plaintext or regexp:: patterns. Query is only used in query mode.",
        );
        const basicFields = itemKeyword.mode === "query"
          ? [
            ["friendly_name", "Friendly Name", "text", "half"],
            ["keyword_query", "Query", "text", "half"],
            ["keyword_filter", "Filter", "text", "full"],
            ["min_price", "Min Price", "number", "third"],
            ["max_price", "Max Price", "number", "third"],
            ["target_price", "Target Price", "number", "third"],
          ]
          : [
            ["friendly_name", "Friendly Name", "text", "half"],
            ["keyword_filter", "Filter", "text", "half"],
            ["min_price", "Min Price", "number", "third"],
            ["max_price", "Max Price", "number", "third"],
            ["target_price", "Target Price", "number", "third"],
          ];
        let priceValidationMsg = null;
        basicFields.forEach(([key, labelText, type, cls]) => {
          const wrapper = document.createElement("div");
          wrapper.className = `field ${cls}`;
          const label = document.createElement("label");
          label.textContent = labelText;
          const labelNode = key === "keyword_filter"
            ? addLabelWithTooltip(
              label,
              "Use plaintext for simple contains match, or prefix with regexp:: for regex matching.",
            )
            : key === "keyword_query"
              ? addLabelWithTooltip(
                label,
                "eBay search query text. Only shown and used when item mode is Query.",
              )
              : label;
          const input = document.createElement("input");
          input.type = type;
          if (key === "keyword_filter") {
            input.value = itemKeyword.filter ?? "";
          } else if (key === "keyword_query") {
            input.value = itemKeyword.query ?? "";
            input.disabled = itemKeyword.mode !== "query";
          } else {
            input.value = item[key] ?? "";
          }
          const validatePriceInputs = () => {
            const msg = getItemPriceValidationMessage(item);
            const isPriceField = key === "min_price" || key === "max_price" || key === "target_price";
            if (isPriceField) {
              if (msg) input.classList.add("invalid");
              else input.classList.remove("invalid");
            }
            priceValidationMsg = msg;
          };
          validatePriceInputs();
          input.addEventListener("change", () => {
            if (type === "number") {
              item[key] = input.value === "" ? null : Number(input.value);
              validatePriceInputs();
            } else {
              if (key === "keyword_filter") {
                itemKeyword.filter = input.value;
              } else if (key === "keyword_query") {
                itemKeyword.query = input.value === "" ? null : input.value;
              } else {
                item[key] = input.value === "" ? null : input.value;
              }
            }
            const currentPriceError = getItemPriceValidationMessage(item);
            if (currentPriceError) {
              setStatus(currentPriceError, "error");
            }
            markPingChanged();
          });
          wrapper.appendChild(labelNode);
          if (key === "keyword_filter") {
            const inlineRow = document.createElement("div");
            inlineRow.className = "field-inline-row";
            inlineRow.appendChild(input);
            const genBtn = document.createElement("button");
            genBtn.type = "button";
            genBtn.className = "tonal";
            genBtn.textContent = "Generate";
            genBtn.addEventListener("click", () => {
              const targetType = keywordMeta.component_type || inferComponentTypeFromKeyword(itemKeyword.filter || "");
              openFilterGenerateModal(keywordIndex, {
                conversion_mode: false,
                force_component_type: targetType && targetType !== "custom" ? targetType : "nvidia_gpu",
                prefill_component_data: reverseParseComponentData(item, targetType && targetType !== "custom" ? targetType : "nvidia_gpu"),
              });
              setStatus("Filter generator opened.", "ok");
            });
            inlineRow.appendChild(genBtn);
            wrapper.appendChild(inlineRow);
          } else {
            wrapper.appendChild(input);
          }
          grid.appendChild(wrapper);
        });
        if (priceValidationMsg) {
          const warn = document.createElement("p");
          warn.className = "hint";
          warn.style.color = "var(--danger)";
          warn.textContent = priceValidationMsg;
          grid.appendChild(warn);
        }

      } else {
        addKeywordSectionHeader(
          "Matching",
          "Filter supports plaintext or regexp:: patterns. Query is only used in query mode.",
        );
        const basicFields = itemKeyword.mode === "query"
          ? [
            ["friendly_name", "Friendly Name", "text", "half"],
            ["keyword_query", "Query", "text", "half"],
            ["keyword_filter", "Filter", "text", "full"],
            ["min_price", "Min Price", "number", "third"],
            ["max_price", "Max Price", "number", "third"],
            ["target_price", "Target Price", "number", "third"],
          ]
          : [
            ["friendly_name", "Friendly Name", "text", "half"],
            ["keyword_filter", "Filter", "text", "half"],
            ["min_price", "Min Price", "number", "third"],
            ["max_price", "Max Price", "number", "third"],
            ["target_price", "Target Price", "number", "third"],
          ];

        let priceValidationMsg = null;
        basicFields.forEach(([key, labelText, type, cls]) => {
          const wrapper = document.createElement("div");
          wrapper.className = `field ${cls}`;

          const label = document.createElement("label");
          label.textContent = labelText;
          const labelNode = key === "keyword_filter"
            ? addLabelWithTooltip(
              label,
              "Use plaintext for simple contains match, or prefix with regexp:: for regex matching.",
            )
            : key === "keyword_query"
              ? addLabelWithTooltip(
                label,
                "eBay search query text. Only shown and used when item mode is Query.",
              )
              : label;

          const input = document.createElement("input");
          input.type = type;
          if (key === "keyword_filter") {
            input.value = itemKeyword.filter ?? "";
          } else if (key === "keyword_query") {
            input.value = itemKeyword.query ?? "";
            input.disabled = itemKeyword.mode !== "query";
          } else {
            input.value = item[key] ?? "";
          }
          const validatePriceInputs = () => {
            const msg = getItemPriceValidationMessage(item);
            const isPriceField = key === "min_price" || key === "max_price" || key === "target_price";
            if (isPriceField) {
              if (msg) input.classList.add("invalid");
              else input.classList.remove("invalid");
            }
            priceValidationMsg = msg;
          };
          validatePriceInputs();
          input.addEventListener("change", () => {
            if (type === "number") {
              item[key] = input.value === "" ? null : Number(input.value);
              validatePriceInputs();
            } else {
              if (key === "keyword_filter") {
                itemKeyword.filter = input.value;
              } else if (key === "keyword_query") {
                itemKeyword.query = input.value === "" ? null : input.value;
              } else {
                item[key] = input.value === "" ? null : input.value;
              }
            }
            const currentPriceError = getItemPriceValidationMessage(item);
            if (currentPriceError) {
              setStatus(currentPriceError, "error");
            }
            markPingChanged();
          });

          wrapper.appendChild(labelNode);
          if (key === "keyword_filter") {
            const inlineRow = document.createElement("div");
            inlineRow.className = "field-inline-row";
            inlineRow.appendChild(input);
            const genBtn = document.createElement("button");
            genBtn.type = "button";
            genBtn.className = "tonal";
            genBtn.textContent = "Generate";
            genBtn.addEventListener("click", () => {
              const targetType = keywordMeta.component_type || inferComponentTypeFromKeyword(itemKeyword.filter || "");
              openFilterGenerateModal(keywordIndex, {
                conversion_mode: false,
                force_component_type: targetType && targetType !== "custom" ? targetType : "nvidia_gpu",
                prefill_component_data: reverseParseComponentData(item, targetType && targetType !== "custom" ? targetType : "nvidia_gpu"),
              });
              setStatus("Filter generator opened.", "ok");
            });
            inlineRow.appendChild(genBtn);
            wrapper.appendChild(inlineRow);
          } else {
            wrapper.appendChild(input);
          }
          grid.appendChild(wrapper);
        });
        if (priceValidationMsg) {
          const warn = document.createElement("p");
          warn.className = "hint";
          warn.style.color = "var(--danger)";
          warn.textContent = priceValidationMsg;
          grid.appendChild(warn);
        }
      }

      addKeywordSectionHeader(
        "Filters",
        "These filters affect notification behavior after an item matches.",
      );
      const dnsWrapper = document.createElement("div");
      dnsWrapper.className = "field full";
      const dnsLabel = document.createElement("label");
      dnsLabel.textContent = "Do not show (Item-level) (Excludes selected tiers from pings)";
      dnsWrapper.appendChild(dnsLabel);

      const dnsSelect = createMultiSelect(
        item.deal_ranges.do_not_show || [],
        dealNames,
        (newValues) => {
          item.deal_ranges.do_not_show = newValues;
          markPingChanged();
        },
        "Select tiers to exclude..."
      );
      dnsWrapper.appendChild(dnsSelect);
      grid.appendChild(dnsWrapper);

      addKeywordSectionHeader(
        "Deal Ranges",
        "Deal tiers are evaluated from min/max and these cutoffs.",
      );
      const dealAssistWrap = document.createElement("div");
      dealAssistWrap.className = "field full";
      const dealAssistRow = document.createElement("div");
      dealAssistRow.className = "button-row no-justify";
      const dealAssistBtn = document.createElement("button");
      dealAssistBtn.type = "button";
      dealAssistBtn.className = "tonal";
      dealAssistBtn.textContent = "Generate Deal Ranges";
      dealAssistBtn.addEventListener("click", () => {
        const targetType = keywordMeta.component_type || inferComponentTypeFromKeyword(itemKeyword.filter || "");
        openAutoGenerateModal(keywordIndex, {
          conversion_mode: false,
          force_component_type: targetType && targetType !== "custom" ? targetType : "nvidia_gpu",
          prefill_component_data: reverseParseComponentData(item, targetType && targetType !== "custom" ? targetType : "nvidia_gpu"),
        });
        setStatus("Deal-ranges assist opened.", "ok");
      });
      dealAssistRow.appendChild(dealAssistBtn);
      dealAssistWrap.appendChild(dealAssistRow);
      grid.appendChild(dealAssistWrap);
      const unifiedTierEditor = createUnifiedTierEditor(item, ping);
      grid.appendChild(unifiedTierEditor);

      card.appendChild(head);
      card.appendChild(grid);
      keywordCardsEl.appendChild(card);
    });

    if (ping.items.length === 0) {
      keywordCardsEl.innerHTML = '<p class="muted">No items for this ping. Add one.</p>';
    }
  }

  function bindTabClicks() {
    document.querySelectorAll(".tab-btn").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        button.classList.add("active");
        const targetId = button.getAttribute("data-tab");
        document.querySelectorAll(".panel").forEach((panel) => {
          panel.classList.toggle("active", panel.id === targetId);
        });

        // Keep backup list fresh without needing a dedicated refresh button.
        if (targetId === "backupsPanel") {
          send({ action: ACTION_GET_BACKUPS });
        }
      });
    });
  }

  function bindActions() {
    // Session extension buttons
    if (btnSessionExtend) {
      btnSessionExtend.addEventListener("click", extendSession);
    }
    if (btnSessionLogout) {
      btnSessionLogout.addEventListener("click", () => {
        // Immediate logout without reload
        setStatus(SESSION_MESSAGES.sessionExpired, "error");
        ws.close();
        state = null;
        originalState = null;
        window.location.href = "/";
      });
    }

    document.getElementById("btnSavePing").addEventListener("click", () => {
      if (!state || !state.pings || !state.pings.length) return;
      if (!hasPendingPingChanges) return;
      
      // Validate before saving
      const validationErrors = validateStateForSave();
      if (validationErrors.length > 0) {
        showError(`Validation failed with ${validationErrors.length} error(s). Please fix the highlighted fields.`);
        validationErrors.forEach(err => {
          console.error(`[Validation] ${err.message}`);
        });
        return;
      }
      
      touchSelectedPingTimestampIfNeeded();
      openSaveDiffDialog(buildSaveParsedPayload());
    });
    document.getElementById("btnDiscard").addEventListener("click", () => discardChanges());
    document.getElementById("btnExport").addEventListener("click", () => send({ action: ACTION_EXPORT_JSON }));

    document.getElementById("btnExportBlocklist").addEventListener("click", () => {
      if (!state.blocklist || !state.blocklist.length) return;
      const content = state.blocklist.join("\n");
      const blob = new Blob([content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "global_blocklist.txt";
      a.click();
      URL.revokeObjectURL(url);
    });

    btnAddBlocklist.addEventListener("click", () => {
      openBlocklistAddDialog();
    });

    btnSaveBlocklist.addEventListener("click", () => {
      send({ action: ACTION_SAVE_BLOCKLIST, items: state.blocklist });
    });

    btnDiscardBlocklist.addEventListener("click", () => {
      state.blocklist = [...originalState.blocklist];
      renderBlocklist();
      updateBlocklistSaveState();
    });

    if (blocklistAddModeCustomEl && blocklistAddModeEl) {
      const dropdown = createSingleSelect(
        blocklistAddModeEl.value || "plain",
        [
          { value: "plain", label: "Plaintext" },
          { value: "regex", label: "Regex" },
        ],
        (newValue) => {
          blocklistAddModeEl.value = newValue;
          applyBlocklistDialogModeToggle();
        }
      );
      blocklistAddModeCustomEl.innerHTML = "";
      blocklistAddModeCustomEl.appendChild(dropdown.container);
      blocklistAddModeDropdown = dropdown;
    }
    if (blocklistAddModeEl) {
      blocklistAddModeEl.addEventListener("change", applyBlocklistDialogModeToggle);
    }
    if (blocklistAddValueEl) {
      blocklistAddValueEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          addBlocklistFromDialog();
        }
      });
    }
    if (btnBlocklistAddCancelEl) {
      btnBlocklistAddCancelEl.addEventListener("click", closeBlocklistAddDialog);
    }
    if (btnBlocklistAddApplyEl) {
      btnBlocklistAddApplyEl.addEventListener("click", addBlocklistFromDialog);
    }
    if (blocklistAddOverlayEl) {
      blocklistAddOverlayEl.addEventListener("click", (e) => {
        if (e.target === blocklistAddOverlayEl) {
          closeBlocklistAddDialog();
        }
      });
    }

    btnAddRoleGroup.addEventListener("click", () => {
      state.self_roles.push({ title: "New Group", roles: [] });
      renderRoleGroups();
      updateRolesSaveState();
    });

    btnSaveRoles.addEventListener("click", () => {
      touchSelectedPingTimestampIfNeeded();
      send(buildSaveParsedPayload());
    });

    btnDiscardRoles.addEventListener("click", () => {
      state.self_roles = JSON.parse(JSON.stringify(originalState.self_roles));
      renderRoleGroups();
      updateRolesSaveState();
    });

    btnSaveSettings.addEventListener("click", () => {
      touchSelectedPingTimestampIfNeeded();
      send(buildSaveParsedPayload());
    });

    btnDiscardSettings.addEventListener("click", () => {
      send({ action: ACTION_GET_STATE });
    });

    document.getElementById("btnDuplicatePing").addEventListener("click", () => {
      if (!state.pings.length) return;
      ensureEditorMetadataForAllPings();
      const copy = JSON.parse(JSON.stringify(state.pings[selectedPingIndex]));
      const metaCopy = cloneJson(state.editor_metadata.pings[selectedPingIndex] || { items: [] });
      state.pings.splice(selectedPingIndex + 1, 0, copy);
      state.editor_metadata.pings.splice(selectedPingIndex + 1, 0, metaCopy);
      selectedPingIndex++;
      renderPingList();
      renderPingDetails();
      markPingChanged();
      setStatus("Ping duplicated.", "ok");
    });

    document.getElementById("btnMovePingUp").addEventListener("click", () => {
      if (selectedPingIndex <= 0) return;
      ensureEditorMetadataForAllPings();
      const item = state.pings.splice(selectedPingIndex, 1)[0];
      state.pings.splice(selectedPingIndex - 1, 0, item);
      const metaItem = state.editor_metadata.pings.splice(selectedPingIndex, 1)[0];
      state.editor_metadata.pings.splice(selectedPingIndex - 1, 0, metaItem);
      selectedPingIndex--;
      renderPingList();
      renderPingDetails();
      markPingChanged();
    });

    document.getElementById("btnMovePingDown").addEventListener("click", () => {
      if (selectedPingIndex >= state.pings.length - 1) return;
      ensureEditorMetadataForAllPings();
      const item = state.pings.splice(selectedPingIndex, 1)[0];
      state.pings.splice(selectedPingIndex + 1, 0, item);
      const metaItem = state.editor_metadata.pings.splice(selectedPingIndex, 1)[0];
      state.editor_metadata.pings.splice(selectedPingIndex + 1, 0, metaItem);
      selectedPingIndex++;
      renderPingList();
      renderPingDetails();
      markPingChanged();
    });

    document.getElementById("btnAddPing").addEventListener("click", () => {
      ensureEditorMetadataForAllPings();
      state.pings.push(createDefaultPing());
      state.editor_metadata.pings.push({ items: [] });
      selectedPingIndex = state.pings.length - 1;
      renderPingList();
      renderPingDetails();
      markPingChanged();
    });

    document.getElementById("btnRemovePing").addEventListener("click", async () => {
      if (!state.pings.length) return;
      const currentPing = state.pings[selectedPingIndex];
      const pingLabel = currentPing?.category_name || `Ping ${selectedPingIndex + 1}`;
      const shouldDelete = await confirmAction(
        "Delete Ping",
        `Delete ${pingLabel}? This cannot be undone except by restoring a backup.`,
        "Delete",
        "danger"
      );
      if (!shouldDelete) return;
      ensureEditorMetadataForAllPings();
      state.pings.splice(selectedPingIndex, 1);
      state.editor_metadata.pings.splice(selectedPingIndex, 1);
      selectedPingIndex = Math.max(0, selectedPingIndex - 1);
      
      // Auto-save the state after removal since it's a high-intent action
      touchSelectedPingTimestampIfNeeded();
      send(buildSaveParsedPayload());
      
      renderPingList();
      renderPingDetails();
      markPingSaved();
    });

    document.getElementById("btnAddKeyword").addEventListener("click", () => {
      if (!state.pings.length) return;
      ensureEditorMetadataForAllPings();
      const ping = state.pings[selectedPingIndex];
      ping.items.push(createDefaultItem());
      state.editor_metadata.pings[selectedPingIndex].items.push(createDefaultKeywordMeta(true));
      renderKeywords(ping);
      markPingChanged();
    });

    btnAutoGenerateCancelEl.addEventListener("click", closeAutoGenerateModal);
    btnFilterGenerateCancelEl.addEventListener("click", closeFilterGenerateModal);
    
    if (autoComponentTypeEl) {
      autoComponentTypeEl.addEventListener("change", () => {
        renderAutoComponentFields();
      });
    }
    if (filterComponentTypeEl) {
      filterComponentTypeEl.addEventListener("change", () => {
        renderFilterComponentFields();
      });
    }

    // Update min price hint and regex preview when target price changes
    autoTargetPriceEl.addEventListener("input", () => {
      updateMinPriceHint();
      updateMaxPriceHint();
      updateAutoGeneratedKeywordPreview();
    });

    autoMinPriceEl.addEventListener("input", () => {
      updateMaxPriceHint();
    });

    btnAutoGenerateApplyEl.addEventListener("click", () => {
      applyAutoGeneratedRanges();
    });
    btnFilterGenerateApplyEl.addEventListener("click", () => {
      applyFilterGeneratedKeyword();
    });

    btnSaveDiffCancelEl.addEventListener("click", () => {
      closeSaveDiffDialog();
      setStatus("Save cancelled.", "warning");
    });
    btnSaveDiffConfirmEl.addEventListener("click", () => {
      if (!pendingSavePayload) return;
      send(pendingSavePayload);
      closeSaveDiffDialog();
      setStatus("Saving ping changes...", "ok");
    });
    saveDiffOverlayEl.addEventListener("click", (e) => {
      if (e.target === saveDiffOverlayEl) {
        closeSaveDiffDialog();
      }
    });

    autoGenerateOverlayEl.addEventListener("click", (e) => {
      if (e.target === autoGenerateOverlayEl) {
        closeAutoGenerateModal();
      }
    });
    filterGenerateOverlayEl.addEventListener("click", (e) => {
      if (e.target === filterGenerateOverlayEl) {
        closeFilterGenerateModal();
      }
    });

    btnArrayAddItemEl.addEventListener("click", addArrayItem);
    arrayNewItemInputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addArrayItem();
      }
    });
    btnArrayCloseEl.addEventListener("click", closeArrayEditor);

    document.getElementById("btnRestoreBackup").addEventListener("click", async () => {
      const filename = backupListEl.value;
      if (!filename) {
        setStatus("Select a backup first", "error");
        return;
      }

      const shouldRestore = await confirmAction(
        "Restore Backup",
        `Restore backup ${filename}? Current values will be replaced.`,
        "Restore"
      );
      if (!shouldRestore) return;
      send({ action: ACTION_RESTORE_BACKUP, filename });
    });

    document.getElementById("btnDeleteBackup").addEventListener("click", async () => {
      const filename = backupListEl.value;
      if (!filename) {
        setStatus("Select a backup first", "error");
        return;
      }

      const shouldDelete = await confirmAction(
        "Delete Backup",
        `Delete backup ${filename}? This cannot be undone.`,
        "Delete",
        "danger"
      );
      if (!shouldDelete) return;
      send({ action: "delete_backup", filename });
    });

    document.getElementById("btnCreateManualBackup").addEventListener("click", async () => {
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const reason = `manual-${timestamp}`;
      
      setModalLoading(true);
      send({ action: "create_manual_backup", reason });
      setStatus("Creating manual backup...", "ok");
    });

    backupListEl.addEventListener("change", () => {
      const filename = backupListEl.value;
      const deleteBtn = document.getElementById("btnDeleteBackup");
      if (deleteBtn) {
        deleteBtn.disabled = !filename;
      }
    });

    document.getElementById("btnSwitchCancel").addEventListener("click", closeSwitchModal);
    document.getElementById("btnSwitchDiscard").addEventListener("click", () => {
      send({ action: "get_state" }); // Reload to discard
      const target = switchTargetIndex;
      closeSwitchModal();
      // Store the target index to switch after state loads
      window.pendingPingSwitch = target;
    });
    document.getElementById("btnSwitchSave").addEventListener("click", () => {
      touchSelectedPingTimestampIfNeeded();
      send(buildSaveParsedPayload());
      const target = switchTargetIndex;
      closeSwitchModal();
      // Store the target index to switch after state loads
      window.pendingPingSwitch = target;
    });

    arrayEditorOverlayEl.addEventListener("click", (e) => {
      if (e.target === arrayEditorOverlayEl) {
        closeArrayEditor();
      }
    });

    confirmOkBtnEl.addEventListener("click", () => resolveConfirm(true));
    confirmCancelBtnEl.addEventListener("click", () => resolveConfirm(false));

    window.addEventListener("beforeunload", (e) => {
      const hasChanges = JSON.stringify(state) !== JSON.stringify(originalState);
      if (hasChanges) {
        e.preventDefault();
        e.returnValue = "";
      }
    });

    document.addEventListener("keydown", (event) => {
      if (!confirmOverlayEl.classList.contains("open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        resolveConfirm(false);
      }
    });

    backupListEl.addEventListener("change", updateBackupMeta);

    document.getElementById("btnToggleBlocklistDiff").addEventListener("click", () => {
      const diffView = document.getElementById("blocklistDiffView");
      if (diffView) {
        diffView.classList.toggle("active");
      }
    });
  }

  function init() {
    bindTabClicks();
    bindActions();
    updatePingSaveButtonState();
    connect();
    
    // Initialize session management
    updateSessionExpiry();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
