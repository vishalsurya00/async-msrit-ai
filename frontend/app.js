/**
 * RIT NEXUS - Sovereign Academic Workspace
 * Dual-Theme Client Application (Reference-Led Art Direction)
 */

(function () {
  'use strict';

  // DOM Elements - Main Workspace
  const chatViewport = document.getElementById('chat-viewport');
  const chatFeed = document.getElementById('chat-feed');
  const emptyState = document.getElementById('empty-state');
  const userInput = document.getElementById('user-input');
  const sendButton = document.getElementById('send-button');
  const btnNewChat = document.getElementById('btn-new-chat');
  const btnTopNew = document.getElementById('btn-top-new');
  const btnThemeToggle = document.getElementById('btn-theme-toggle');
  const brandHomeTrigger = document.getElementById('brand-home-trigger');
  const btnSidebarToggle = document.getElementById('btn-sidebar-toggle');
  const btnSidebarClose = document.getElementById('btn-sidebar-close');
  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');
  const statusEnginePill = document.getElementById('status-engine-pill');
  const statusText = document.getElementById('status-text');
  const statusPulseDot = document.getElementById('status-pulse-dot');
  const topBarTitle = document.getElementById('top-bar-title');
  const conversationsList = document.getElementById('conversations-list');
  const btnClearHistory = document.getElementById('btn-clear-history');

  // DOM Elements - Student Identity & Profile Surface
  const btnOpenProfile = document.getElementById('btn-open-profile');
  const profileModalBackdrop = document.getElementById('profile-modal-backdrop');
  const btnCloseProfile = document.getElementById('btn-close-profile');
  const identityAvatarText = document.getElementById('identity-avatar-text');
  const identityDisplayName = document.getElementById('identity-display-name');
  const identityDisplayUsn = document.getElementById('identity-display-usn');
  const modalAvatarText = document.getElementById('modal-avatar-text');
  const modalHeroName = document.getElementById('modal-hero-name');
  const modalHeroUsn = document.getElementById('modal-hero-usn');
  const modalStatusBadge = document.getElementById('modal-status-badge');
  const modalStatusText = document.getElementById('modal-status-text');

  // Profile Form Inputs
  const profileNameInput = document.getElementById('profile-name-input');
  const profileUsnEdit = document.getElementById('profile-usn-edit');
  const profileBranchInput = document.getElementById('profile-branch-input');
  const profileSemInput = document.getElementById('profile-sem-input');
  const profileYearInput = document.getElementById('profile-year-input');
  const profileStatusSelect = document.getElementById('profile-status-select');
  const profileEmailInput = document.getElementById('profile-email-input');
  const profileDobInput = document.getElementById('profile-dob-input');
  const profilePhoneInput = document.getElementById('profile-phone-input');
  const btnSaveProfile = document.getElementById('btn-save-profile');
  const btnToggleAuth = document.getElementById('btn-toggle-auth');
  const btnAuthText = document.getElementById('btn-auth-text');

  // Storage Keys
  const STORAGE_KEY_THEME = 'rit_nexus_theme';
  const STORAGE_KEY_STUDENT_PROFILE = 'rit_nexus_student_profile';
  const STORAGE_KEY_CONVERSATIONS = 'rit_nexus_conversations';
  const STORAGE_KEY_ACTIVE_CONV = 'rit_nexus_active_conv_id';

  let currentTheme = 'dark';
  let isSubmitting = false;
  let conversations = [];
  let activeConversationId = null;
  let isAuthenticated = true;

  // Student Profile Default State
  let studentProfile = {
    name: 'Sujeet Kamatagi',
    usn: '1MS24CS001',
    branch: 'Computer Science and Engineering',
    semester: '4th Semester',
    year: '2024-2028',
    status: 'Enrolled (Active)',
    email: 'sujeet.k@msrit.edu',
    dob: '2004-05-15',
    phone: '+91 9876543210',
    isAuthenticated: true
  };

  /**
   * Helper: Calculate initials monogram from Person Name
   * e.g., "Sujeet Kamatagi" -> "SK", "Rahul Sharma" -> "RS", fallback -> "ST"
   */
  function getInitialsFromName(name, fallbackUsn) {
    if (!name || typeof name !== 'string' || !name.trim()) {
      if (fallbackUsn && fallbackUsn.trim() && fallbackUsn !== 'anonymous') {
        return fallbackUsn.trim().substring(0, 2).toUpperCase();
      }
      return 'ST';
    }
    const clean = name.trim();
    const parts = clean.split(/\s+/).filter(Boolean);
    if (parts.length === 1) {
      return parts[0].substring(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  // Application Initialization
  function init() {
    initTheme();
    loadSavedProfile();
    loadConversations();
    setupEventListeners();
    checkSystemHealth();

    // Restore active conversation or initialize clean workspace
    const savedActiveId = localStorage.getItem(STORAGE_KEY_ACTIVE_CONV);
    if (savedActiveId && conversations.some(c => c.id === savedActiveId)) {
      selectConversation(savedActiveId);
    } else {
      startNewConversation();
    }
  }

  // --------------------------------------------------------------------------
  // Theme Management (Dark / Light)
  // --------------------------------------------------------------------------
  function initTheme() {
    try {
      const savedTheme = localStorage.getItem(STORAGE_KEY_THEME);
      if (savedTheme === 'light' || savedTheme === 'dark') {
        currentTheme = savedTheme;
      } else {
        currentTheme = 'dark'; // default theme
      }
    } catch (e) {
      currentTheme = 'dark';
    }
    applyTheme(currentTheme);
  }

  function applyTheme(theme) {
    currentTheme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEY_THEME, theme);
    } catch (e) {
      // Storage unavailable
    }
  }

  function toggleTheme() {
    const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(nextTheme);
  }

  // --------------------------------------------------------------------------
  // Profile Management
  // --------------------------------------------------------------------------
  function loadSavedProfile() {
    try {
      const data = localStorage.getItem(STORAGE_KEY_STUDENT_PROFILE);
      if (data) {
        studentProfile = Object.assign(studentProfile, JSON.parse(data));
      }
    } catch (e) {
      // Use in-memory defaults
    }

    if (studentProfile.isAuthenticated === false || studentProfile.usn === 'anonymous') {
      isAuthenticated = false;
    } else {
      isAuthenticated = true;
    }

    updateIdentityUI();
  }

  function saveProfileToStorage() {
    try {
      studentProfile.isAuthenticated = isAuthenticated;
      localStorage.setItem(STORAGE_KEY_STUDENT_PROFILE, JSON.stringify(studentProfile));
    } catch (e) {
      // Storage unavailable
    }
    updateIdentityUI();
  }

  function updateIdentityUI() {
    const isGuest = !isAuthenticated;
    const displayName = isGuest ? 'Guest Student' : (studentProfile.name || 'Student');
    const displayUsn = isGuest ? 'Local Session' : (studentProfile.usn || '1MS24CS001');
    const monogram = isGuest ? 'ST' : getInitialsFromName(studentProfile.name, studentProfile.usn);

    // Sidebar Identity Anchor
    if (identityDisplayName) identityDisplayName.textContent = displayName;
    if (identityDisplayUsn) identityDisplayUsn.textContent = displayUsn;
    if (identityAvatarText) identityAvatarText.textContent = monogram;

    // Slide-Over Profile Surface
    if (modalAvatarText) modalAvatarText.textContent = monogram;
    if (modalHeroName) modalHeroName.textContent = displayName;
    if (modalHeroUsn) modalHeroUsn.textContent = displayUsn;

    if (modalStatusText) {
      modalStatusText.textContent = isGuest ? 'Signed Out' : (studentProfile.status || 'Active Local Profile');
    }
    if (modalStatusBadge) {
      modalStatusBadge.style.color = isGuest ? 'var(--text-muted)' : 'var(--accent-emerald)';
      const pip = modalStatusBadge.querySelector('.status-pip');
      if (pip) pip.style.background = isGuest ? 'var(--text-muted)' : 'var(--accent-emerald)';
    }

    if (btnAuthText) {
      btnAuthText.textContent = isGuest ? 'Sign In / Connect Profile' : 'Sign Out';
    }

    // Populate Form Controls
    if (profileNameInput) profileNameInput.value = studentProfile.name || '';
    if (profileUsnEdit) profileUsnEdit.value = studentProfile.usn || '';
    if (profileBranchInput) profileBranchInput.value = studentProfile.branch || '';
    if (profileSemInput) profileSemInput.value = studentProfile.semester || '';
    if (profileYearInput) profileYearInput.value = studentProfile.year || '';
    if (profileStatusSelect) profileStatusSelect.value = studentProfile.status || 'Enrolled (Active)';
    if (profileEmailInput) profileEmailInput.value = studentProfile.email || '';
    if (profileDobInput) profileDobInput.value = studentProfile.dob || '';
    if (profilePhoneInput) profilePhoneInput.value = studentProfile.phone || '';
  }

  function handleSaveProfileClick() {
    studentProfile.name = profileNameInput ? profileNameInput.value.trim() : '';
    studentProfile.usn = profileUsnEdit ? profileUsnEdit.value.trim() : '1MS24CS001';
    studentProfile.branch = profileBranchInput ? profileBranchInput.value.trim() : '';
    studentProfile.semester = profileSemInput ? profileSemInput.value : '';
    studentProfile.year = profileYearInput ? profileYearInput.value.trim() : '';
    studentProfile.status = profileStatusSelect ? profileStatusSelect.value : 'Enrolled (Active)';
    studentProfile.email = profileEmailInput ? profileEmailInput.value.trim() : '';
    studentProfile.dob = profileDobInput ? profileDobInput.value : '';
    studentProfile.phone = profilePhoneInput ? profilePhoneInput.value.trim() : '';
    isAuthenticated = true;

    saveProfileToStorage();

    if (btnSaveProfile) {
      const originalText = btnSaveProfile.innerHTML;
      btnSaveProfile.innerHTML = '<span>Saved</span>';
      btnSaveProfile.style.background = 'var(--accent-strong)';
      btnSaveProfile.style.color = '#ffffff';
      setTimeout(() => {
        btnSaveProfile.innerHTML = originalText;
        btnSaveProfile.style.background = '';
        btnSaveProfile.style.color = '';
        closeProfileModal();
      }, 700);
    }
  }

  function toggleAuthenticationState() {
    if (isAuthenticated) {
      isAuthenticated = false;
    } else {
      isAuthenticated = true;
      if (!studentProfile.usn || studentProfile.usn === 'anonymous') {
        studentProfile.usn = profileUsnEdit && profileUsnEdit.value.trim() ? profileUsnEdit.value.trim() : '1MS24CS001';
      }
    }
    saveProfileToStorage();
  }

  // --------------------------------------------------------------------------
  // Conversation History Management
  // --------------------------------------------------------------------------
  function loadConversations() {
    try {
      const data = localStorage.getItem(STORAGE_KEY_CONVERSATIONS);
      conversations = data ? JSON.parse(data) : [];
      if (!Array.isArray(conversations)) conversations = [];
    } catch (e) {
      conversations = [];
    }
    renderConversationsSidebar();
  }

  function saveConversations() {
    try {
      localStorage.setItem(STORAGE_KEY_CONVERSATIONS, JSON.stringify(conversations));
      if (activeConversationId) {
        localStorage.setItem(STORAGE_KEY_ACTIVE_CONV, activeConversationId);
      } else {
        localStorage.removeItem(STORAGE_KEY_ACTIVE_CONV);
      }
    } catch (e) {
      // Storage quota or disabled
    }
    renderConversationsSidebar();
  }

  function renderConversationsSidebar() {
    if (!conversationsList) return;

    if (conversations.length === 0) {
      conversationsList.innerHTML = '<div class="empty-threads-note">No previous conversations</div>';
      if (btnClearHistory) btnClearHistory.style.display = 'none';
      return;
    }

    if (btnClearHistory) btnClearHistory.style.display = 'block';

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const yesterdayStart = todayStart - 86400000;

    const clusters = {
      today: [],
      yesterday: [],
      earlier: []
    };

    conversations.forEach(conv => {
      const convTime = conv.createdAt ? new Date(conv.createdAt).getTime() : 0;
      if (convTime >= todayStart) {
        clusters.today.push(conv);
      } else if (convTime >= yesterdayStart) {
        clusters.yesterday.push(conv);
      } else {
        clusters.earlier.push(conv);
      }
    });

    let html = '';

    const renderCluster = (title, items) => {
      if (items.length === 0) return '';
      return `
        <div class="threads-date-cluster">
          <div class="threads-cluster-title">${title}</div>
          ${items.map(conv => {
            const isActive = conv.id === activeConversationId ? ' active' : '';
            const safeTitle = escapeHtml(conv.title || 'Untitled Conversation');
            return `
              <div class="thread-item-row${isActive}" data-id="${conv.id}">
                <span class="thread-item-text" title="${safeTitle}">${safeTitle}</span>
                <button class="btn-delete-thread-item" data-delete-id="${conv.id}" title="Delete thread" aria-label="Delete thread">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                  </svg>
                </button>
              </div>
            `;
          }).join('')}
        </div>
      `;
    };

    html += renderCluster('Today', clusters.today);
    html += renderCluster('Yesterday', clusters.yesterday);
    html += renderCluster('Earlier', clusters.earlier);

    conversationsList.innerHTML = html;
  }

  function selectConversation(id) {
    const conv = conversations.find(c => c.id === id);
    if (!conv) {
      startNewConversation();
      return;
    }

    activeConversationId = id;
    localStorage.setItem(STORAGE_KEY_ACTIVE_CONV, id);

    if (topBarTitle) {
      topBarTitle.textContent = conv.title || 'RIT NEXUS';
    }

    // Render feed
    if (chatFeed) {
      chatFeed.innerHTML = '';
      if (conv.messages && conv.messages.length > 0) {
        if (emptyState) emptyState.style.display = 'none';
        conv.messages.forEach(msg => {
          if (msg.role === 'user') {
            appendUserMessageToDOM(msg.text);
          } else {
            appendAssistantMessageToDOM(msg);
          }
        });
        scrollToBottom();
      } else {
        if (emptyState) emptyState.style.display = 'flex';
      }
    }

    renderConversationsSidebar();
    closeSidebar();
  }

  function deleteConversation(id, e) {
    if (e) e.stopPropagation();
    conversations = conversations.filter(c => c.id !== id);
    if (activeConversationId === id) {
      startNewConversation();
    } else {
      saveConversations();
    }
  }

  function clearAllConversations() {
    conversations = [];
    activeConversationId = null;
    saveConversations();
    startNewConversation();
  }

  /**
   * CANONICAL NEW CONVERSATION FUNCTION
   */
  function startNewConversation() {
    activeConversationId = null;
    localStorage.removeItem(STORAGE_KEY_ACTIVE_CONV);

    isSubmitting = false;

    if (topBarTitle) {
      topBarTitle.textContent = 'RIT NEXUS';
    }

    if (chatFeed) {
      chatFeed.innerHTML = '';
    }

    if (emptyState) {
      emptyState.style.display = 'flex';
    }

    if (userInput) {
      userInput.value = '';
      userInput.style.height = '24px';
      userInput.focus();
    }

    toggleSendButtonState();
    renderConversationsSidebar();
    closeSidebar();
  }

  // Expose canonical function globally
  window.startNewConversation = startNewConversation;
  window.startNewChat = startNewConversation; // Backwards compatibility

  // Event Listeners Setup
  function setupEventListeners() {
    // Theme Switcher Toggle
    if (btnThemeToggle) {
      btnThemeToggle.addEventListener('click', toggleTheme);
    }

    // Textarea input & autogrowth
    if (userInput) {
      userInput.addEventListener('input', function () {
        this.style.height = 'auto';
        const newHeight = Math.min(this.scrollHeight, 160);
        this.style.height = (newHeight > 24 ? newHeight : 24) + 'px';
        toggleSendButtonState();
      });

      userInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSubmit();
        }
      });
    }

    // Send Button
    if (sendButton) {
      sendButton.addEventListener('click', handleSubmit);
    }

    // Canonical New Conversation Triggers
    if (btnNewChat) {
      btnNewChat.addEventListener('click', startNewConversation);
    }
    if (btnTopNew) {
      btnTopNew.addEventListener('click', startNewConversation);
    }
    if (brandHomeTrigger) {
      brandHomeTrigger.addEventListener('click', startNewConversation);
    }

    // Clear History Button
    if (btnClearHistory) {
      btnClearHistory.addEventListener('click', () => {
        if (confirm('Clear all conversation history?')) {
          clearAllConversations();
        }
      });
    }

    // Profile Surface Open / Close
    if (btnOpenProfile) {
      btnOpenProfile.addEventListener('click', openProfileModal);
      btnOpenProfile.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openProfileModal();
        }
      });
    }

    if (btnCloseProfile) {
      btnCloseProfile.addEventListener('click', closeProfileModal);
    }

    if (profileModalBackdrop) {
      profileModalBackdrop.addEventListener('click', (e) => {
        if (e.target === profileModalBackdrop) {
          closeProfileModal();
        }
      });
    }

    // Save Profile Form Action
    if (btnSaveProfile) {
      btnSaveProfile.addEventListener('click', handleSaveProfileClick);
    }

    // Toggle Sign In / Sign Out
    if (btnToggleAuth) {
      btnToggleAuth.addEventListener('click', toggleAuthenticationState);
    }

    // Sidebar Mobile Drawer Toggles
    if (btnSidebarToggle && sidebar && sidebarBackdrop) {
      btnSidebarToggle.addEventListener('click', () => {
        sidebar.classList.add('open');
        sidebarBackdrop.classList.add('active');
      });
    }

    if (btnSidebarClose && sidebar && sidebarBackdrop) {
      btnSidebarClose.addEventListener('click', closeSidebar);
    }

    if (sidebarBackdrop) {
      sidebarBackdrop.addEventListener('click', closeSidebar);
    }

    // Delegated click handler on conversation list
    if (conversationsList) {
      conversationsList.addEventListener('click', (e) => {
        const deleteBtn = e.target.closest('[data-delete-id]');
        if (deleteBtn) {
          const delId = deleteBtn.getAttribute('data-delete-id');
          deleteConversation(delId, e);
          return;
        }

        const item = e.target.closest('.thread-item-row');
        if (item) {
          const convId = item.getAttribute('data-id');
          if (convId) {
            selectConversation(convId);
          }
        }
      });
    }

    // Dashboard Cards, Metric Cards, Chips, and Inquiry Buttons Delegated Handler
    document.addEventListener('click', (e) => {
      // 1. Chip click with specific query
      const chip = e.target.closest('.ref-chip[data-query]');
      if (chip) {
        e.stopPropagation();
        const query = chip.getAttribute('data-query');
        if (query && userInput) {
          userInput.value = query;
          userInput.style.height = 'auto';
          userInput.style.height = Math.min(userInput.scrollHeight, 160) + 'px';
          toggleSendButtonState();
          handleSubmit();
        }
        return;
      }

      // 2. Inquiry pill button click
      const pillBtn = e.target.closest('.inquiry-pill-btn[data-query]');
      if (pillBtn) {
        e.stopPropagation();
        const query = pillBtn.getAttribute('data-query');
        if (query && userInput) {
          userInput.value = query;
          userInput.style.height = 'auto';
          userInput.style.height = Math.min(userInput.scrollHeight, 160) + 'px';
          toggleSendButtonState();
          handleSubmit();
        }
        return;
      }

      // 3. Metric card or Dashboard card click
      const promptCard = e.target.closest('[data-prompt]');
      if (promptCard) {
        const prompt = promptCard.getAttribute('data-prompt');
        if (prompt && userInput) {
          userInput.value = prompt;
          userInput.style.height = 'auto';
          userInput.style.height = Math.min(userInput.scrollHeight, 160) + 'px';
          toggleSendButtonState();
          handleSubmit();
        }
      }
    });
  }

  function openProfileModal() {
    updateIdentityUI();
    document.body.classList.add('profile-open');
    if (profileModalBackdrop) {
      profileModalBackdrop.classList.add('active');
    }
  }

  function closeProfileModal() {
    document.body.classList.remove('profile-open');
    if (profileModalBackdrop) {
      profileModalBackdrop.classList.remove('active');
    }
  }

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('active');
  }

  function toggleSendButtonState() {
    if (!sendButton || !userInput) return;
    const hasText = userInput.value.trim().length > 0;
    sendButton.disabled = isSubmitting || !hasText;
  }

  // System Health Check (GET /health)
  async function checkSystemHealth() {
    try {
      const resp = await fetch('/health', { method: 'GET' });
      if (resp.ok) {
        if (statusText) statusText.textContent = 'Connected';
        if (statusEnginePill) statusEnginePill.textContent = 'Ollama 7B';
        if (statusPulseDot) statusPulseDot.style.background = 'var(--accent-emerald)';
      }
    } catch (e) {
      if (statusText) statusText.textContent = 'Offline';
      if (statusEnginePill) {
        statusEnginePill.textContent = 'Standby';
        statusEnginePill.style.color = 'var(--text-muted)';
      }
      if (statusPulseDot) statusPulseDot.style.background = 'var(--accent-rose)';
    }
  }

  // Main Submission Handler (POST /ask API Contract)
  async function handleSubmit() {
    if (isSubmitting) return;
    const query = userInput.value.trim();
    if (!query) return;

    const studentIdToSend = isAuthenticated ? (studentProfile.usn || '1MS24CS001') : 'anonymous';

    // Create session if not active
    if (!activeConversationId) {
      const newId = 'conv_' + Date.now();
      const generatedTitle = query.length > 36 ? query.substring(0, 36) + '...' : query;
      const newConv = {
        id: newId,
        title: generatedTitle,
        createdAt: new Date().toISOString(),
        messages: []
      };
      conversations.unshift(newConv);
      activeConversationId = newId;
      if (topBarTitle) topBarTitle.textContent = generatedTitle;
      saveConversations();
    }

    // Hide empty state
    if (emptyState) {
      emptyState.style.display = 'none';
    }

    // Append User Message to UI
    appendUserMessageToDOM(query);

    // Save to current conversation in memory
    const activeConv = conversations.find(c => c.id === activeConversationId);
    if (activeConv) {
      activeConv.messages.push({
        role: 'user',
        text: query
      });
      saveConversations();
    }

    // Reset textarea
    userInput.value = '';
    userInput.style.height = '24px';
    isSubmitting = true;
    toggleSendButtonState();

    // Show Quiet Typing Indicator
    const typingIndicator = showTypingIndicator();
    scrollToBottom();

    const startTime = performance.now();

    try {
      // API call strictly adhering to POST /ask contract
      const response = await fetch('/ask', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: query,
          student_id: studentIdToSend
        })
      });

      const elapsedSec = ((performance.now() - startTime) / 1000).toFixed(1);
      removeTypingIndicator(typingIndicator);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorDetail = errorData.detail || `Server error code ${response.status}`;
        const errorMsg = {
          role: 'assistant',
          answer: `**Unable to complete request**\n\n${errorDetail}`,
          action_taken: 'error',
          latency: `${elapsedSec}s`,
          isError: true
        };
        appendAssistantMessageToDOM(errorMsg);
        if (activeConv) {
          activeConv.messages.push(errorMsg);
          saveConversations();
        }
      } else {
        const payload = await response.json();
        const assistantMsg = {
          role: 'assistant',
          answer: payload.answer || 'No response content received.',
          action_taken: payload.action_taken || 'answer',
          sources: payload.sources || [],
          latency: `${elapsedSec}s`
        };
        appendAssistantMessageToDOM(assistantMsg);
        if (activeConv) {
          activeConv.messages.push(assistantMsg);
          saveConversations();
        }
      }
    } catch (err) {
      removeTypingIndicator(typingIndicator);
      const networkErrorMsg = {
        role: 'assistant',
        answer: `**Connection Unavailable**\n\nCould not reach local service: \`${err.message}\`.\n\nPlease verify that your local FastAPI server and Ollama instance are active.`,
        action_taken: 'network_error',
        latency: '0.0s',
        isError: true
      };
      appendAssistantMessageToDOM(networkErrorMsg);
      if (activeConv) {
        activeConv.messages.push(networkErrorMsg);
        saveConversations();
      }
    } finally {
      isSubmitting = false;
      toggleSendButtonState();
      scrollToBottom();
    }
  }

  // Render User Message
  function appendUserMessageToDOM(text) {
    if (!chatFeed) return;
    const row = document.createElement('div');
    row.className = 'message-cluster-row user';
    row.innerHTML = `
      <div class="user-capsule">${escapeHtml(text).replace(/\n/g, '<br>')}</div>
    `;
    chatFeed.appendChild(row);
  }

  // Render Assistant Message
  function appendAssistantMessageToDOM(data) {
    if (!chatFeed) return;
    const { answer, action_taken, sources = [], latency, isError = false } = data;

    const row = document.createElement('div');
    row.className = 'message-cluster-row assistant';

    const actionTag = getActionTagText(action_taken, isError);
    const latencyText = latency ? `<span class="assistant-latency-label">${latency}</span>` : '';

    const parsedContent = formatMarkdown(answer);

    // Sources Disclosure HTML
    let sourcesHtml = '';
    if (sources && sources.length > 0) {
      sourcesHtml = `
        <div class="sources-disclosure-block">
          <button class="btn-sources-disclosure" type="button" aria-expanded="false">
            <div class="sources-left-heading">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
              </svg>
              <span>Sources &bull; ${sources.length}</span>
            </div>
            <svg class="sources-toggle-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <div class="sources-cards-flow" style="display: none;">
            ${sources.map(src => `
              <div class="source-reference-card">
                <div>
                  <div class="source-subject-title">${escapeHtml(src.subject || 'Reference')}</div>
                  <div class="source-path-code">${escapeHtml(src.file_path || 'MSRIT Repository')}</div>
                </div>
                <span class="source-verification-badge">Verified</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    }

    const canvasClass = isError ? 'assistant-response-canvas error-canvas' : 'assistant-response-canvas';

    row.innerHTML = `
      <div class="assistant-meta-header">
        <div class="assistant-brand-glyph">
          <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:16px;height:16px;">
            <rect x="3" y="3" width="22" height="22" rx="6" fill="currentColor" fill-opacity="0.1" stroke="currentColor" stroke-width="1.6"/>
            <path d="M8 20V8L15 16V8" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <path d="M15 20V12L20 8" stroke="var(--accent-primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="15" cy="16" r="1.5" fill="var(--accent-primary)"/>
          </svg>
        </div>
        <span class="assistant-identity-title">RIT NEXUS</span>
        ${actionTag}
        ${latencyText}
      </div>
      <div class="${canvasClass}">
        ${parsedContent}
        ${sourcesHtml}
      </div>
      <div class="assistant-utility-footer">
        <button class="btn-copy-response-text" title="Copy response" aria-label="Copy response">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy</span>
        </button>
      </div>
    `;

    // Toggle sources accordion
    const toggleBtn = row.querySelector('.btn-sources-disclosure');
    const sourcesFlow = row.querySelector('.sources-cards-flow');
    if (toggleBtn && sourcesFlow) {
      toggleBtn.addEventListener('click', () => {
        const isHidden = sourcesFlow.style.display === 'none';
        sourcesFlow.style.display = isHidden ? 'flex' : 'none';
        toggleBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
        toggleBtn.classList.toggle('open', isHidden);
      });
    }

    // Copy message button
    const copyBtn = row.querySelector('.btn-copy-response-text');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        copyToClipboard(answer, copyBtn);
      });
    }

    // Code block copy listeners
    row.querySelectorAll('.btn-copy-code').forEach(btn => {
      btn.addEventListener('click', function () {
        const codeText = this.getAttribute('data-code') || '';
        copyToClipboard(codeText, this);
      });
    });

    chatFeed.appendChild(row);
  }

  // Understated metadata indicator
  function getActionTagText(action, isError) {
    if (isError) {
      return '<span class="assistant-action-label error">error</span>';
    }
    switch (action) {
      case 'answer_question':
        return '<span class="assistant-action-label">academic retrieval</span>';
      case 'summarize_notes':
        return '<span class="assistant-action-label">course notes</span>';
      case 'lookup_branch':
        return '<span class="assistant-action-label">department directory</span>';
      case 'lookup_club':
        return '<span class="assistant-action-label">campus clubs</span>';
      case 'lookup_faculty':
        return '<span class="assistant-action-label">faculty directory</span>';
      case 'get_student_profile':
        return '<span class="assistant-action-label">student record</span>';
      case 'update_student_profile':
        return '<span class="assistant-action-label">updated record</span>';
      case 'conversation':
        return '<span class="assistant-action-label">workspace</span>';
      case 'network_error':
        return '<span class="assistant-action-label error">offline</span>';
      default:
        return action ? `<span class="assistant-action-label">${escapeHtml(action)}</span>` : '';
    }
  }

  // Quiet typing indicator
  function showTypingIndicator() {
    if (!chatFeed) return null;
    const row = document.createElement('div');
    row.className = 'message-cluster-row assistant typing-cluster-row';
    row.id = 'active-typing-indicator';

    row.innerHTML = `
      <div class="typing-dot-pips">
        <div class="typing-pip"></div>
        <div class="typing-pip"></div>
        <div class="typing-pip"></div>
      </div>
    `;

    chatFeed.appendChild(row);
    return row;
  }

  function removeTypingIndicator(el) {
    if (el && el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }

  function scrollToBottom() {
    if (chatViewport) {
      chatViewport.scrollTo({
        top: chatViewport.scrollHeight,
        behavior: 'smooth'
      });
    }
  }

  // Copy helper with visual feedback
  function copyToClipboard(text, buttonElement) {
    if (!navigator.clipboard) {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    } else {
      navigator.clipboard.writeText(text);
    }

    if (buttonElement) {
      const originalHtml = buttonElement.innerHTML;
      buttonElement.innerHTML = `
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>Copied</span>
      `;
      setTimeout(() => {
        buttonElement.innerHTML = originalHtml;
      }, 1600);
    }
  }

  // HTML entity escaper
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Client-Side Markdown Parser
  function formatMarkdown(rawText) {
    if (!rawText) return '';

    let text = String(rawText);

    // 1. Extract fenced code blocks first
    const codeBlocks = [];
    text = text.replace(/```([a-zA-Z0-9_\-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      const id = `__CODE_BLOCK_${codeBlocks.length}__`;
      const cleanLang = lang.trim() || 'plaintext';
      const escapedCode = escapeHtml(code.trim());
      const rawCodeData = escapeHtml(code.trim());
      const blockHtml = `
        <div class="code-block-container">
          <div class="code-block-header">
            <span>${cleanLang}</span>
            <button class="btn-copy-code" data-code="${rawCodeData}">Copy</button>
          </div>
          <pre><code>${escapedCode}</code></pre>
        </div>
      `;
      codeBlocks.push(blockHtml);
      return id;
    });

    // 2. Escape standard HTML for remaining text
    let safe = escapeHtml(text);

    // 3. Inline code blocks `code`
    safe = safe.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');

    // 4. Bold **text** and *italic*
    safe = safe.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    safe = safe.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // 5. Headings, Lists, Blockquotes, Tables, Paragraphs
    const lines = safe.split('\n');
    let html = '';
    let inList = false;
    let listType = 'ul';
    let inTable = false;
    let tableHeaderDone = false;

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i].trim();

      // Check for code block placeholder
      if (line.startsWith('__CODE_BLOCK_') && line.endsWith('__')) {
        if (inList) { html += `</${listType}>`; inList = false; }
        if (inTable) { html += '</tbody></table></div>'; inTable = false; }
        const index = parseInt(line.replace('__CODE_BLOCK_', '').replace('__', ''), 10);
        html += codeBlocks[index] || '';
        continue;
      }

      // Headings
      if (/^###\s+/.test(line)) {
        if (inList) { html += `</${listType}>`; inList = false; }
        html += `<h3>${line.replace(/^###\s+/, '')}</h3>`;
        continue;
      }
      if (/^##\s+/.test(line)) {
        if (inList) { html += `</${listType}>`; inList = false; }
        html += `<h2>${line.replace(/^##\s+/, '')}</h2>`;
        continue;
      }
      if (/^#\s+/.test(line)) {
        if (inList) { html += `</${listType}>`; inList = false; }
        html += `<h1>${line.replace(/^#\s+/, '')}</h1>`;
        continue;
      }

      // Blockquote
      if (line.startsWith('&gt;') || line.startsWith('>')) {
        if (inList) { html += `</${listType}>`; inList = false; }
        const quoteContent = line.replace(/^(&gt;|>)\s*/, '');
        html += `<blockquote>${quoteContent}</blockquote>`;
        continue;
      }

      // Tables
      if (line.startsWith('|') && line.endsWith('|')) {
        if (inList) { html += `</${listType}>`; inList = false; }
        const cells = line.split('|').slice(1, -1).map(c => c.trim());
        
        if (cells.every(c => /^[-:]+$/.test(c))) {
          tableHeaderDone = true;
          continue;
        }

        if (!inTable) {
          inTable = true;
          tableHeaderDone = false;
          html += '<div class="table-wrapper"><table><thead><tr>';
          cells.forEach(c => { html += `<th>${c}</th>`; });
          html += '</tr></thead><tbody>';
        } else {
          html += '<tr>';
          cells.forEach(c => { html += `<td>${c}</td>`; });
          html += '</tr>';
        }
        continue;
      } else if (inTable) {
        html += '</tbody></table></div>';
        inTable = false;
      }

      // Unordered lists
      if (/^[-*]\s+/.test(line)) {
        if (!inList || listType !== 'ul') {
          if (inList) html += `</${listType}>`;
          html += '<ul>';
          inList = true;
          listType = 'ul';
        }
        html += `<li>${line.replace(/^[-*]\s+/, '')}</li>`;
        continue;
      }

      // Ordered lists
      if (/^\d+\.\s+/.test(line)) {
        if (!inList || listType !== 'ol') {
          if (inList) html += `</${listType}>`;
          html += '<ol>';
          inList = true;
          listType = 'ol';
        }
        html += `<li>${line.replace(/^\d+\.\s+/, '')}</li>`;
        continue;
      }

      if (inList) {
        html += `</${listType}>`;
        inList = false;
      }

      // Normal paragraph
      if (line.length > 0) {
        html += `<p>${line}</p>`;
      }
    }

    if (inList) html += `</${listType}>`;
    if (inTable) html += '</tbody></table></div>';

    return html;
  }

  // Initialize once DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
