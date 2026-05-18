# Adding New Component Types

File to edit: `static/config-editor/app.js`. Pull this up in your editor.

## 1. Register component type

Edit `AUTO_COMPONENT_TYPES` and add your new entry (value + label). Formatted like this: `{ value: "nvme_ssd", label: "NVMe SSD" }`

Location:
- `static/config-editor/app.js` (`AUTO_COMPONENT_TYPES`)

## 2. Define component data/structure/fields

Add default fields for your type in the component default-data logic.

Locations:
- `getDefaultComponentData` function: Add a default here
- `autoComponentState`: Simply add a call to `getDefaultComponentData("component_id")`

Both should include the same keys so UI and generation stay in sync.

## 3. Rendering fields

Locations:
- `renderAutoComponentFields` function: add fields that need to be provided to generate filter
- Item field rendering in `renderKeywords(...)` (if you want editable typed fields on cards)

## 4. Generate the filter

Implement regex pattern generation logic in `generateKeywordFromComponent` function

## 5. Add reverse prefill support (optional)

If you want "Generate" buttons to prefill from existing item data, update:

- `reverseParseComponentData(...)`
- `inferComponentTypeFromKeyword(...)` (if needed)

## 6. Validate with quick manual checks

Test the workflow in the UI to make sure everything works as expected.
