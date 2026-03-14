/* global document */

(function () {
    function findHelpTextElement(selectElement) {
        const describedBy = selectElement.getAttribute("aria-describedby");

        if (describedBy) {
            for (const id of describedBy.split(/\s+/)) {
                if (!id) {
                    continue;
                }
                const element = document.getElementById(id);
                if (element) {
                    return element;
                }
            }
        }

        const container = selectElement.closest(
            ".field-campaign_mode, .form-row, .form-group, .tabular, .flex, .mb-6"
        );

        if (container) {
            const candidate = container.querySelector(
                "[id$='_helptext'], .help, .helptext, p.help, div.leading-relaxed.mt-2.text-xs"
            );
            if (candidate) {
                return candidate;
            }
        }

        const wrapper = selectElement.closest(".grow.relative");
        if (wrapper) {
            const candidate = wrapper.querySelector("div.leading-relaxed.mt-2.text-xs");
            if (candidate) {
                return candidate;
            }
        }

        let sibling = selectElement.nextElementSibling;
        while (sibling) {
            if (
                sibling.matches(
                    "[id$='_helptext'], .help, .helptext, p.help, div.leading-relaxed.mt-2.text-xs"
                )
            ) {
                return sibling;
            }
            sibling = sibling.nextElementSibling;
        }

        return null;
    }

    function updateCampaignModeHelpText(selectElement, helpTextElement) {
        const mode = selectElement.value || "";
        const normalizedMode = mode.toLowerCase().replaceAll("_", "-");
        const helpText =
            selectElement.getAttribute(`data-help-text-${normalizedMode}`) ||
            selectElement.getAttribute("data-default-help-text") ||
            "";

        helpTextElement.textContent = helpText;
    }

    function initializeCampaignModeHelpText() {
        const selectElement = document.getElementById("id_campaign_mode");
        if (!selectElement) {
            return;
        }

        const helpTextElement = findHelpTextElement(selectElement);
        if (!helpTextElement) {
            return;
        }

        const update = function () {
            updateCampaignModeHelpText(selectElement, helpTextElement);
        };

        selectElement.addEventListener("change", update);
        update();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeCampaignModeHelpText);
    } else {
        initializeCampaignModeHelpText();
    }
})();