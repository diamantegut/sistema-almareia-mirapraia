(function(window) {
    function getContainer(selectorId) {
        return document.getElementById(selectorId);
    }

    function init(selectorId, options) {
        const container = getContainer(selectorId);
        if (!container) return null;
        const startInput = container.querySelector('.rps-start');
        const endInput = container.querySelector('.rps-end');
        const opts = options || {};
        if (startInput && opts.startDate) startInput.value = opts.startDate;
        if (endInput && opts.endDate) endInput.value = opts.endDate;
        if (startInput && endInput && !endInput.value && startInput.value) endInput.value = startInput.value;
        if (opts.weekdays && Array.isArray(opts.weekdays)) {
            const wanted = new Set(opts.weekdays.map(v => String(v || '').toLowerCase()));
            container.querySelectorAll('.rps-weekday').forEach(el => {
                el.checked = wanted.has(String(el.value || '').toLowerCase());
            });
        }
        if (startInput && endInput) {
            startInput.addEventListener('change', function() {
                if (!endInput.value || endInput.value < startInput.value) endInput.value = startInput.value;
            });
            endInput.addEventListener('change', function() {
                if (startInput.value && endInput.value && endInput.value < startInput.value) {
                    endInput.value = startInput.value;
                }
            });
        }
        return getValue(selectorId);
    }

    function getValue(selectorId) {
        const container = getContainer(selectorId);
        if (!container) return { start_date: '', end_date: '', weekdays: [] };
        const startInput = container.querySelector('.rps-start');
        const endInput = container.querySelector('.rps-end');
        const weekdays = Array.from(container.querySelectorAll('.rps-weekday:checked')).map(el => el.value);
        const startDate = startInput ? (startInput.value || '') : '';
        const endDate = endInput ? (endInput.value || startDate) : startDate;
        return {
            start_date: startDate,
            end_date: endDate || startDate,
            weekdays
        };
    }

    function setValue(selectorId, value) {
        const container = getContainer(selectorId);
        if (!container || !value) return;
        const startInput = container.querySelector('.rps-start');
        const endInput = container.querySelector('.rps-end');
        if (startInput && value.start_date) startInput.value = value.start_date;
        if (endInput && value.end_date) endInput.value = value.end_date;
        if (Array.isArray(value.weekdays)) {
            const wanted = new Set(value.weekdays.map(v => String(v || '').toLowerCase()));
            container.querySelectorAll('.rps-weekday').forEach(el => {
                el.checked = wanted.has(String(el.value || '').toLowerCase());
            });
        }
    }

    window.RevenuePeriodSelector = {
        init,
        getValue,
        setValue
    };
})(window);
