CORPORATE POWERPOINT TEMPLATES
==============================

Put your approved template files in this folder (.potx or .pptx) and register
each one in ..\templates.json:

  "file":        file name in this folder, e.g. "corporate.potx"
  "layouts":     names of the layouts to use, exactly as shown in PowerPoint
                 (View > Slide Master), e.g.
                 {"title": "Title Slide", "content": "Title Only"}
                 "content" should be a layout with a title and an empty area.
  "title_size":  headline size in points (28 suits most 16:9 templates);
                 set to null to keep the template's own title size.
  "accent", "ink", "muted", "tile", "warn":
                 hex colours (no #) used for the shapes and charts the studio
                 draws. Copy them from the template's theme colours.
  "font":        font for the shapes and charts the studio draws.

Any sample slides inside the template are ignored; only its masters, layouts,
theme and fonts are used.

If a file listed in templates.json is missing, the studio uses a clean built-in
16:9 template with the colours above, so it keeps working until the real
templates are copied in. Changes take effect on the next export; no restart needed.
