(function () {
  const form = document.querySelector('#tracking-form');
  const barcodeInput = form?.querySelector('#barcode');
  const resultsPanel = document.querySelector('[data-results]');
  const summaryContainer = document.querySelector('[data-summary]');
  const timelineContainer = document.querySelector('[data-timeline]');
  const rawSection = document.querySelector('[data-raw]');
  const rawPre = rawSection?.querySelector('pre');
  const errorBox = document.querySelector('[data-error]');
  const successBox = document.querySelector('[data-success]');
  const loadingOverlay = document.querySelector('[data-loading]');

  const hasFetch = typeof window.fetch === 'function';

  const readJSONScript = (id) => {
    const script = document.getElementById(id);
    if (!script) return null;
    try {
      const text = script.textContent?.trim();
      if (!text) return null;
      return JSON.parse(text);
    } catch (error) {
      console.warn('Failed to parse JSON payload', error);
      return null;
    }
  };

  const toggleLoading = (state) => {
    if (!loadingOverlay) return;
    loadingOverlay.hidden = !state;
  };

  const clearSuccess = () => {
    if (successBox) {
      successBox.hidden = true;
      successBox.textContent = '';
    }
  };

  const showError = (message) => {
    if (!errorBox) return;
    errorBox.textContent = message || '';
    errorBox.hidden = !message;
    if (barcodeInput) {
      barcodeInput.classList.toggle('has-error', Boolean(message));
    }
    if (message && resultsPanel) {
      resultsPanel.hidden = false;
    }
  };

  const showSuccess = (message) => {
    if (!successBox) return;
    successBox.textContent = message || '';
    successBox.hidden = !message;
  };

  const renderEmpty = () => {
    if (!timelineContainer) return;
    timelineContainer.innerHTML = '';
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    const title = document.createElement('h3');
    title.textContent = 'هنوز اطلاعاتی ثبت نشده است';
    const message = document.createElement('p');
    message.textContent = 'پس از ثبت اولین رویداد برای مرسوله، جزئیات در این بخش نمایش داده می‌شود.';
    empty.appendChild(title);
    empty.appendChild(message);
    timelineContainer.appendChild(empty);
  };

  const renderSummary = (data) => {
    if (!summaryContainer) return;
    summaryContainer.innerHTML = '';

    const items = [
      { label: 'کد رهگیری', value: data.barcode },
      { label: 'وضعیت فعلی', value: data.current_status },
      { label: 'فرستنده', value: data.sender },
      { label: 'گیرنده', value: data.receiver },
    ].filter((item) => Boolean(item.value));

    if (!items.length) {
      const placeholder = document.createElement('div');
      placeholder.className = 'empty-state';
      const title = document.createElement('h3');
      title.textContent = 'اطلاعات خلاصه‌ای یافت نشد';
      const message = document.createElement('p');
      message.textContent = 'پس از ثبت جزئیات بیشتر، خلاصه وضعیت در این بخش به نمایش درخواهد آمد.';
      placeholder.appendChild(title);
      placeholder.appendChild(message);
      summaryContainer.appendChild(placeholder);
      return;
    }

    const fragment = document.createDocumentFragment();
    items.forEach((item, index) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'summary-item reveal';
      wrapper.style.animationDelay = `${index * 0.08}s`;

      const label = document.createElement('span');
      label.className = 'summary-label';
      label.textContent = item.label;

      const value = document.createElement('span');
      value.className = 'summary-value';
      value.textContent = item.value;

      wrapper.appendChild(label);
      wrapper.appendChild(value);
      fragment.appendChild(wrapper);
    });

    summaryContainer.appendChild(fragment);
  };

  const renderTimeline = (events) => {
    if (!timelineContainer) return;
    timelineContainer.innerHTML = '';

    if (!events || !events.length) {
      renderEmpty();
      return;
    }

    const list = document.createElement('ol');
    list.className = 'timeline-list';

    events.forEach((event, index) => {
      const item = document.createElement('li');
      item.className = 'timeline-item reveal';
      item.style.animationDelay = `${index * 0.06}s`;

      const meta = document.createElement('div');
      meta.className = 'timeline-meta';

      const date = document.createElement('span');
      date.className = 'timeline-date';
      date.textContent = event.date || '-';

      const time = document.createElement('span');
      time.className = 'timeline-time';
      time.textContent = event.time || '-';

      meta.appendChild(date);
      meta.appendChild(time);

      const content = document.createElement('div');
      content.className = 'timeline-content';

      const title = document.createElement('h3');
      title.textContent = event.description || 'وضعیت نامشخص';

      const location = document.createElement('p');
      location.className = 'muted';
      location.textContent = event.location || 'مکان نامشخص';

      content.appendChild(title);
      content.appendChild(location);

      item.appendChild(meta);
      item.appendChild(content);
      list.appendChild(item);
    });

    timelineContainer.appendChild(list);
  };

  const renderRawResponse = (data) => {
    if (!rawSection || !rawPre) return;
    const payload = data.raw_response || data;
    rawPre.textContent = JSON.stringify(payload, null, 2);
    rawSection.hidden = false;
  };

  const renderResult = (data) => {
    if (!resultsPanel) return;
    resultsPanel.hidden = false;
    clearSuccess();
    showError('');
    renderSummary(data);
    renderTimeline(data.events || []);
    renderRawResponse(data);
    showSuccess('اطلاعات مرسوله با موفقیت به‌روزرسانی شد.');
  };

  const hydrateInitialState = () => {
    const initialResult = readJSONScript('initial-tracking');
    const initialError = readJSONScript('initial-error');
    if (initialResult) {
      renderResult(initialResult);
      clearSuccess();
    }
    if (initialError) {
      showError(initialError);
    }
  };

  if (barcodeInput) {
    barcodeInput.addEventListener('input', () => {
      if (!barcodeInput.value.trim()) {
        barcodeInput.classList.remove('has-error');
      }
      clearSuccess();
      showError('');
    });
  }

  if (form && hasFetch) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearSuccess();

      const barcode = barcodeInput?.value.trim();
      if (!barcode) {
        showError('لطفاً کد رهگیری را وارد کنید.');
        return;
      }

      toggleLoading(true);
      showError('');

      try {
        const response = await fetch('/api/track', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: JSON.stringify({ barcode }),
        });

        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.error || 'امکان دریافت اطلاعات وجود ندارد.');
        }

        renderResult(payload);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'خطای ناشناخته رخ داد.';
        showError(message);
      } finally {
        toggleLoading(false);
      }
    });
  }

  hydrateInitialState();
})();
