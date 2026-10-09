(function (root) {
  'use strict';
  var validEmail = function(v) {
    var s = String(v||'').trim();
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
  };
  var validPhone = function(v) {
    var s = String(v||'').replace(/[\s\-().\/]/g, '');
    if (s.charAt(0)==='+') {
      s = s.slice(1);
    }
    return /^[0-9]{6,15}$/.test(s);
  };
  var bookingPrefillUrl = function(provider, url, name, email, notes) {
    var keys = {calcom: ['name', 'email', 'notes'], calendly: ['name', 'email']}[provider];
    if (!keys) return url;
    var h = url.indexOf('#'), frag = h < 0 ? '' : url.slice(h + 1), rest = h < 0 ? url : url.slice(0, h);
    var q = rest.indexOf('?'), base = q < 0 ? rest : rest.slice(0, q), query = q < 0 ? '' : rest.slice(q + 1);
    var vals = {name: name, email: email, notes: notes}, added = [], used = {};
    keys.forEach(function (k) { var v = (vals[k] || '').trim(); if (v) { added.push([k, v]); used[k] = 1; } });
    var dec = function (s) { return decodeURIComponent(s.replace(/\+/g, ' ')); };
    var pairs = query.split('&').filter(Boolean).map(function (p) { var i = p.indexOf('='); return i < 0 ? [dec(p), ''] : [dec(p.slice(0, i)), dec(p.slice(i + 1))]; }).filter(function (p) { return !used[p[0]]; }).concat(added);
    var qs = pairs.map(function (p) { return encodeURIComponent(p[0]) + '=' + encodeURIComponent(p[1]); }).join('&');
    return base + (qs ? '?' + qs : '') + (frag ? '#' + frag : '');
  };
  var buildPayload = function(state, cfg, pageUrl, startedMs, nowMs) {
    function t(v) { return String(v || '').trim(); }
    return {
      name: t(state.name),
      phone: t(state.phone),
      email: t(state.email),
      service: t(state.service),
      message: t(state.message),
      callback_window: state.mode === 'callback' ? t(state.window) : '',
      booking_provider: state.mode === 'booking' && cfg.booking ? cfg.booking.provider : '',
      consent: !!state.consent,
      page_url: pageUrl,
      ts: new Date(nowMs).toISOString(),
      hp_fax: state.hp || '',
      elapsed_ms: nowMs - startedMs
    };
  };
  var mailtoHref = function(email, business, payload) {
    var lines = [];
    if (payload.service) lines.push('Service: ' + payload.service);
    if (payload.name) lines.push('Name: ' + payload.name);
    if (payload.phone) lines.push('Phone: ' + payload.phone);
    if (payload.email) lines.push('Email: ' + payload.email);
    if (payload.callback_window) {
      lines.push('Callback window: ' + payload.callback_window);
    } else if (payload.booking_provider) {
      lines.push('Booking: ' + payload.booking_provider);
    }
    if (payload.message) lines.push('Message: ' + payload.message);
    lines.push('Consent to be contacted: ' + (payload.consent ? 'yes' : 'no'));
    lines.push('Page: ' + payload.page_url);
    return 'mailto:' + email + '?subject=' + encodeURIComponent('Callback request via website') + '&body=' + encodeURIComponent(lines.join('\n'));
  };
  var api = {validEmail: validEmail, validPhone: validPhone, bookingPrefillUrl: bookingPrefillUrl, buildPayload: buildPayload, mailtoHref: mailtoHref};
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
  if (typeof document === 'undefined') { return; }
  root.ReviewForgeChat = api;
  var cfg, state = {}, step = 'service', startedMs = 0, dialog, log, form, hpInput, launcher;
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([tabindex="-1"]),textarea,select';
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function add(parent, child) { parent.appendChild(child); return child; }
  function say(cls, text) { add(log, el('p', 'rfc-msg ' + cls, text)); log.scrollTop = log.scrollHeight; }
  function bot(t) { say('rfc-bot', t); }  function me(t) { say('rfc-me', t); }
  function button(text, cls, onClick) {
    var b = el('button', cls, text);
    b.type = onClick ? 'button' : 'submit';
    if (onClick) b.onclick = onClick;
    return b;
  }
  function chips(labels, onPick) {
    var row = el('div', 'rfc-chips');
    for (var i = 0; i < labels.length; i++) {
      var l = labels[i];
      var b = button(l, 'rfc-chip', (function(label) { return function() { onPick(label); }; })(l));
      add(row, b);
    }
    return add(form, row);
  }
  function input(labelText, attrs) {
    var lab = add(form, el('label', null, labelText + ' '));
    var i = el(attrs.tag || 'input');
    for (var k in attrs) if (k !== 'tag') i.setAttribute(k, attrs[k]);
    add(lab, i);
    return i;
  }
  function errBox() {
    var e = add(form, el('p', 'rfc-err'));
    e.setAttribute('role', 'alert');
    return e;
  }
  function fail(i, msg) {
    form.querySelector('.rfc-err').textContent = msg;
    i.setAttribute('aria-invalid', 'true');
    i.focus();
  }
  function go(next) {
    step = next;
    render();
  }
  function render() {
    clear(form);
    switch (step) {
      case 'service':
        bot("Hi. I'm an automated assistant for " + cfg.business + ". I can pass a callback or booking request on. I can't answer questions about prices or availability.");
        bot("What do you need help with?");
        chips(cfg.services.concat(['Something else']), function(s) {
          me(s);
          state.service = s;
          go(s === 'Something else' ? 'other' : 'name');
        });
        break;
      case 'other':
        input('Briefly, what do you need? (optional)', {tag: 'textarea', maxlength: 500, rows: 3, name: 'message'});
        add(form, button('Continue', 'rfc-primary'));
        break;
      case 'name':
        bot("What's your name?");
        input('Name', {type: 'text', autocomplete: 'name', maxlength: 80, required: 'required', name: 'name'});
        errBox();
        add(form, button('Continue', 'rfc-primary'));
        break;
      case 'contact':
        bot("Which phone number should " + cfg.business + " call? An email address is optional.");
        input('Phone', {type: 'tel', autocomplete: 'tel', required: 'required', name: 'phone'});
        input('Email (optional)', {type: 'email', autocomplete: 'email', name: 'email'});
        errBox();
        add(form, button('Continue', 'rfc-primary'));
        break;
      case 'mode':
        if (!cfg.booking) {
          state.mode = 'callback';
          return go('window');
        }
        bot("Would you like a call back, or to book a time yourself?");
        chips(['Call me back', 'Book a time'], function(c) {
          me(c);
          if (c === 'Book a time') {
            state.mode = 'booking';
            bot("The " + cfg.booking.label + " booking page will open in a new tab when you send this request. Available times are shown there.");
            go('consent');
          } else {
            state.mode = 'callback';
            go('window');
          }
        });
        break;
      case 'window':
        if (state.mode === 'callback') {
          bot("When is a good time for a call?");
          chips(cfg.callback_windows, function(w) {
            me(w);
            state.window = w;
            go('consent');
          });
        } else {
          go('consent');
        }
        break;
      case 'consent':
        var lab = add(form, el('label', 'rfc-check'));
        var cb = add(lab, el('input'));
        cb.type = 'checkbox';
        cb.id = 'rfc-consent';
        add(lab, document.createTextNode(' I agree that ' + cfg.business + ' may use these details to contact me about this request.'));
        if (cfg.privacy_url) {
          add(lab, document.createTextNode(' '));
          var a = add(lab, el('a', null, 'Privacy policy'));
          a.href = cfg.privacy_url;
          a.target = '_blank';
          a.rel = 'noopener';
        }
        errBox();
        add(form, button('Continue', 'rfc-primary'));
        break;
      case 'summary':
        bot("Please check your request:");
        var dl = add(form, el('dl', 'rfc-summary'));
        var rows = [
          ['Service', state.service],
          ['Details', state.message],
          ['Name', state.name],
          ['Phone', state.phone],
          ['Email', state.email],
          state.mode === 'booking' ? ['Booking', cfg.booking.label] : ['Call back', state.window],
          ['Consent', state.consent ? 'Yes' : 'No']
        ];
        for (var i = 0; i < rows.length; i++) {
          var row = rows[i];
          if (row[1]) {
            add(dl, el('dt', null, row[0]));
            add(dl, el('dd', null, row[1]));
          }
        }
        add(form, button('Send request', 'rfc-primary'));
        add(form, button('Start over', 'rfc-chip', function() {
          state = {};
          clear(log);
          go('service');
        }));
        break;
    }
    var f = form.querySelector(FOCUSABLE);
    if (f && !dialog.hidden) f.focus();
  }
  function onSubmit(e) {
    e.preventDefault();
    switch (step) {
      case 'other':
        state.message = form.querySelector('textarea').value.trim();
        if (state.message) me(state.message);
        go('name');
        break;
      case 'name':
        var i = form.querySelector('input[name="name"]');
        var name = i.value.trim();
        if (!name) {
          fail(i, 'Please enter your name.');
        } else {
          state.name = name;
          me(name);
          go('contact');
        }
        break;
      case 'contact':
        var phoneInput = form.querySelector('input[name="phone"]');
        var emailInput = form.querySelector('input[name="email"]');
        var phone = phoneInput.value.trim();
        var email = emailInput.value.trim();
        if (!validPhone(phone)) {
          fail(phoneInput, 'Please enter a valid phone number.');
        } else if (email && !validEmail(email)) {
          fail(emailInput, 'That email address doesn\'t look right.');
        } else {
          state.phone = phone;
          state.email = email;
          me(phone + (email ? ' · ' + email : ''));
          go('mode');
        }
        break;
      case 'consent':
        var cb = form.querySelector('#rfc-consent');
        if (cfg.consent_required && !cb.checked) {
          fail(cb, 'Please tick the box so ' + cfg.business + ' may contact you.');
        } else {
          state.consent = cb.checked;
          go('summary');
        }
        break;
      case 'summary':
        send();
        break;
    }
  }
  function done(ok, payload) {
    clear(form);
    step = 'done';
    if (ok) {
      bot('Thanks, ' + cfg.business + ' has your request.');
      if (state.mode === 'booking') bot('Pick a time on the booking page that opened in a new tab.');
      return;
    }
    if (cfg.email) {
      bot("The request couldn't be sent from here. You can send it by email instead:");
      var m = add(form, el('a', 'rfc-primary', 'Email the request'));
      m.href = mailtoHref(cfg.email, cfg.business, payload);
    }
    bot('Or call ' + cfg.phone + '.');
    var t = add(form, el('a', null, cfg.phone));
    t.href = cfg.tel;
  }
  function send() {
    state.hp = hpInput.value;
    var p = buildPayload(state, cfg, location.origin + location.pathname, startedMs, Date.now());
    if (state.mode === 'booking') window.open(bookingPrefillUrl(cfg.booking.provider, cfg.booking.url, state.name, state.email, state.service + (state.message ? ': ' + state.message : '')), '_blank', 'noopener');
    if (p.hp_fax || p.elapsed_ms < (cfg.min_seconds || 3) * 1000) return done(true, p);
    if (!cfg.endpoint) return done(false, p);
    var b = form.querySelector('.rfc-primary');
    b.disabled = true;
    b.textContent = 'Sending…';
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    if (ctl) setTimeout(function () { ctl.abort(); }, 10000);
    fetch(cfg.endpoint, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(p),
      signal: ctl ? ctl.signal : undefined
    }).then(function (r) { done(r.ok, p); }, function () { done(false, p); });
  }
  function open() {
    dialog.hidden = false;
    launcher.setAttribute('aria-expanded', 'true');
    document.documentElement.classList.add('rfc-open');
    if (!startedMs) startedMs = Date.now();
    if (!log.firstChild) render();
    var f = form.querySelector(FOCUSABLE) || dialog.querySelector('.rfc-close');
    if (f) f.focus();
  }
  function close() {
    dialog.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    document.documentElement.classList.remove('rfc-open');
    launcher.focus();
  }
  function onKey(e) {
    if (!dialog || dialog.hidden) return;
    if (e.key === 'Escape') return close();
    if (e.key !== 'Tab') return;
    var list = dialog.querySelectorAll(FOCUSABLE);
    if (!list.length) return;
    var first = list[0];
    var last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      last.focus();
      e.preventDefault();
    } else if (!e.shiftKey && document.activeElement === last) {
      first.focus();
      e.preventDefault();
    }
  }
  function attrs(node, map) {
    for (var k in map) node.setAttribute(k, map[k]);
    return node;
  }
  function init() {
    var configEl = document.getElementById('rf-chat-config');
    if (!configEl) return;
    try {
      cfg = JSON.parse(configEl.textContent);
    } catch (e) {
      return;
    }
    launcher = add(document.body, button('Request a callback', 'rfc-launcher', open));
    attrs(launcher, {'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'aria-controls': 'rfc-dialog'});
    dialog = add(document.body, el('div', 'rfc-dialog'));
    dialog.id = 'rfc-dialog';
    attrs(dialog, {'role': 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'rfc-title'});
    dialog.hidden = true;
    var head = add(dialog, el('div', 'rfc-head'));
    var title = add(head, el('h2', 'rfc-title', 'Automated assistant'));
    title.id = 'rfc-title';
    var sub = add(head, el('p', 'rfc-sub', cfg.business + ' · callback request'));
    var closeBtn = add(head, button('×', 'rfc-close', close));
    attrs(closeBtn, {'aria-label': 'Close'});
    log = add(dialog, el('div', 'rfc-log'));
    attrs(log, {'role': 'log', 'aria-live': 'polite'});
    form = add(dialog, el('form', 'rfc-step'));
    form.noValidate = true;
    form.onsubmit = onSubmit;
    var hp = add(dialog, el('div', 'rfc-hp'));
    attrs(hp, {'aria-hidden': 'true'});
    var hpLabel = add(hp, el('label', null, 'Fax '));
    hpInput = add(hpLabel, el('input'));
    hpInput.name = 'hp_fax';
    hpInput.tabIndex = -1;
    hpInput.autocomplete = 'off';
    var telP = add(dialog, el('p', 'rfc-tel', 'Prefer to talk? Call '));
    var telLink = add(telP, el('a', null, cfg.phone));
    telLink.href = cfg.tel;
    document.addEventListener('keydown', onKey);
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})(typeof window !== 'undefined' ? window : this);
