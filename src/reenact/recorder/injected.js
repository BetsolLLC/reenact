/**
 * Reenact in-page recorder.
 * Injected via page.add_init_script(). Posts events to Python via window.__reenact_event().
 * Guard prevents double-injection on SPA soft-navs.
 */
(function () {
  if (window.__reenactInjected) return;
  window.__reenactInjected = true;

  // ── ARIA helpers ──────────────────────────────────────────────────────────

  function getImplicitRole(el) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();

    if (tag === 'button') return 'button';
    if (tag === 'input') {
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'range') return 'slider';
      if (type === 'number') return 'spinbutton';
      // text / email / url / tel / search / password / '' → textbox
      return 'textbox';
    }
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'img') return 'img';
    if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tag)) return 'heading';
    if (tag === 'nav') return 'navigation';
    if (tag === 'main') return 'main';
    if (tag === 'form') return 'form';
    return null;
  }

  function getAccessibleName(el) {
    // Priority: aria-label → aria-labelledby → label[for] → wrapping label → placeholder → title → alt → name → text
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/)
        .map(id => { const n = document.getElementById(id); return n ? n.textContent.trim() : ''; })
        .filter(Boolean).join(' ');
      if (text) return text;
    }

    if (el.id) {
      try {
        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (label) {
          const clone = label.cloneNode(true);
          clone.querySelectorAll('input,select,textarea').forEach(function(n) { n.remove(); });
          const t = clone.textContent.trim();
          if (t) return t;
        }
      } catch (_) {}
    }

    const parentLabel = el.closest('label');
    if (parentLabel) {
      const clone = parentLabel.cloneNode(true);
      clone.querySelectorAll('input,select,textarea').forEach(function(n) { n.remove(); });
      const t = clone.textContent.trim();
      if (t) return t;
    }

    if (el.getAttribute('placeholder') && el.getAttribute('placeholder').trim())
      return el.getAttribute('placeholder').trim();
    if (el.getAttribute('title') && el.getAttribute('title').trim())
      return el.getAttribute('title').trim();
    if (el.getAttribute('alt') && el.getAttribute('alt').trim())
      return el.getAttribute('alt').trim();
    if (el.getAttribute('name') && el.getAttribute('name').trim())
      return el.getAttribute('name').trim();

    const text = (el.textContent || '').trim();
    if (text && text.length < 120) return text;

    return null;
  }

  // ── Element serialiser ────────────────────────────────────────────────────

  function serializeElement(el) {
    return {
      tagName: el.tagName || null,
      id: el.id || null,
      name: el.getAttribute ? (el.getAttribute('name') || null) : null,
      type: el.getAttribute ? (el.getAttribute('type') || null) : null,
      value: (el.value !== undefined && el.value !== null) ? el.value : null,
      textContent: (el.textContent || '').trim().slice(0, 200) || null,
      placeholder: el.getAttribute ? (el.getAttribute('placeholder') || null) : null,
      ariaLabel: el.getAttribute ? (el.getAttribute('aria-label') || null) : null,
      ariaLabelledby: el.getAttribute ? (el.getAttribute('aria-labelledby') || null) : null,
      role: el.getAttribute ? (el.getAttribute('role') || null) : null,
      dataTestId: el.getAttribute ? (
        el.getAttribute('data-testid') ||
        el.getAttribute('data-test-id') ||
        el.getAttribute('data-cy') ||
        el.getAttribute('data-test') ||
        null
      ) : null,
      className: el.className || null,
      href: el.href || null,
      implicitRole: getImplicitRole(el),
      accessibleName: getAccessibleName(el),
    };
  }

  // ── Emit ─────────────────────────────────────────────────────────────────

  function emit(data) {
    if (typeof window.__reenact_event === 'function') {
      window.__reenact_event(data);
    }
  }

  // ── Input: capture final value on blur, not every keystroke ──────────────

  var _prevInputValues = new WeakMap();

  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      _prevInputValues.set(el, el.value);
    }
  }, true);

  document.addEventListener('blur', function (e) {
    var el = e.target;
    if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
    var type = (el.getAttribute('type') || '').toLowerCase();
    if (['checkbox', 'radio', 'button', 'submit', 'reset', 'file'].includes(type)) return;
    var prev = _prevInputValues.get(el);
    // Emit if value changed OR if no prior value tracked (e.g. autofill)
    if (prev !== el.value) {
      emit({
        type: 'input',
        element: serializeElement(el),
        value: el.value,
        url: window.location.href,
      });
    }
  }, true);

  // ── Select / checkbox / radio ─────────────────────────────────────────────

  document.addEventListener('change', function (e) {
    var el = e.target;
    if (el instanceof HTMLSelectElement) {
      emit({
        type: 'select',
        element: serializeElement(el),
        value: el.value,
        url: window.location.href,
      });
    } else if (el instanceof HTMLInputElement) {
      var type = (el.getAttribute('type') || '').toLowerCase();
      if (type === 'checkbox' || type === 'radio') {
        emit({
          type: 'click',
          element: serializeElement(el),
          url: window.location.href,
        });
      }
    }
  }, true);

  // ── Click ─────────────────────────────────────────────────────────────────

  document.addEventListener('click', function (e) {
    // Walk up DOM to find a meaningful target (up to 5 levels)
    var target = e.target;
    for (var i = 0; i < 5 && target && target !== document.body; i++) {
      var tag = target.tagName ? target.tagName.toLowerCase() : '';
      var type = target.getAttribute ? (target.getAttribute('type') || '').toLowerCase() : '';
      var role = target.getAttribute ? (target.getAttribute('role') || '').toLowerCase() : '';
      if (
        tag === 'button' || tag === 'a' ||
        (tag === 'input' && ['button', 'submit', 'reset', 'checkbox', 'radio'].includes(type)) ||
        role === 'button' || role === 'link' || role === 'menuitem' || role === 'tab'
      ) {
        break;
      }
      target = target.parentElement;
    }
    if (!target) target = e.target;

    var finalTag = target.tagName ? target.tagName.toLowerCase() : '';
    var finalType = target.getAttribute ? (target.getAttribute('type') || '').toLowerCase() : '';
    // Skip plain text inputs — handled via blur
    if ((finalTag === 'input' || finalTag === 'textarea') &&
        !['checkbox', 'radio', 'button', 'submit', 'reset'].includes(finalType)) {
      return;
    }

    emit({
      type: 'click',
      element: serializeElement(target),
      url: window.location.href,
    });
  }, true);

  // ── Special keys (Escape, Tab; Enter only on non-input elements) ──────────

  document.addEventListener('keydown', function (e) {
    if (!['Enter', 'Escape', 'Tab'].includes(e.key)) return;
    var el = e.target;
    // Skip Enter on inputs (navigation / blur handles it)
    if (e.key === 'Enter' && (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
    emit({
      type: 'key',
      key: e.key,
      element: serializeElement(el),
      url: window.location.href,
    });
  }, true);

})();
