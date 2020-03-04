const $ = require('jquery');

const Filters = function ($toolbar) {
    this.$toolbar = $toolbar;
};

Filters.prototype = {
    initFiltersInteraction: function($toolbar) {
        $toolbar.find('.changelist-filter-select').each(function() {
            const $select = $(this);
            const multiple = $select.attr('multiple');

            if (multiple) {
                $select.data('previous-options', $select.find('option:selected'));
            }

            $select.on('change', function() {
                const $select = $(this);
                let $selectedOption = $select.find('option:selected');

                if (multiple) {
                    if ($select.data('previous-options').length < $selectedOption.length) {
                        $selectedOption = $selectedOption.filter(function (index, option) {
                            return $select.data('previous-options').filter(function(index, initialOption) {
                                    return initialOption === option;
                                }).length === 0;
                        });
                    } else if ($select.data('previous-options').length > $selectedOption.length) {
                        $selectedOption = $select.data('previous-options').filter(function(index, initialOption) {
                            return $selectedOption.filter(function (index, option) {
                                    return initialOption === option;
                                }).length === 0;
                        });
                    }

                    $select.data('previous-options', $select.find('option:selected'));
                }

                const url = $selectedOption.data('url');
                const querysetLookup = $select.data('queryset--lookup');

                if (url) {
                    document.location = $selectedOption.data('url');
                } else if (querysetLookup) {
                    document.location = '?' + querysetLookup + '=' + $selectedOption.val();
                }
            });
        });
    },
    run: function() {
        try {
            this.initFiltersInteraction(this.$toolbar);
        } catch (e) {
            console.error(e, e.stack);
        }
    }
};

$(document).ready(function() {
    $('#toolbar').each(function() {
        new Filters($(this)).run();
    });
});
