---
description: Template and frontend conventions for the WithThanks dashboard UI
applyTo: "charity/templates/**,assets/**"
---

# Frontend / Templates Instructions

## Template Architecture
- Base layout: `charity/templates/base_dashboard.html` (authenticated pages).
- Sub-layouts in `charity/templates/layouts/`.
- All templates use Django template language (DTL) — NOT Jinja2.
- Template tags: `charity/templatetags/charity_extras.py`.

## Template Structure
```
charity/templates/
├── base_dashboard.html      ← Main authenticated layout (nav, sidebar)
├── dashboard.html           ← Dashboard page
├── layouts/                 ← Shared layout fragments
├── campaigns/               ← Campaign CRUD templates
├── charity/                 ← Charity-specific pages
├── analytics/               ← Analytics dashboard templates
├── emails/                  ← Email templates (sent to donors)
└── ...                      ← Feature-specific templates
```

## Tailwind CSS
- Styling is 100% Tailwind CSS utility classes.
- Source CSS: `assets/src/styles.css` (Tailwind directives).
- Compiled CSS output: `css/tailwind.css` (managed by `django-tailwind-cli`).
- Build command: `uv run python manage.py tailwind build`.
- Watch mode: `uv run python manage.py tailwind watch`.
- **Do NOT write custom CSS** unless absolutely necessary. Use Tailwind utilities.

## Tailwind Class Conventions
- Form inputs: `class="saas-input"` or explicit Tailwind classes.
- Buttons: Use Tailwind button patterns (e.g., `bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded`).
- Cards: `bg-white rounded-lg shadow p-6`.
- Responsive: Use `sm:`, `md:`, `lg:` prefixes for responsive design.

## Template Patterns
- Always extend base layout:
  ```html
  {% extends "base_dashboard.html" %}
  {% block content %}
    <!-- Page content -->
  {% endblock %}
  ```
- Load custom tags:
  ```html
  {% load charity_extras %}
  ```
- Use `{% url 'name' %}` for URL references — never hardcode paths.
- Use `{% csrf_token %}` in all forms.
- Use Django messages framework for flash notifications:
  ```html
  {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
  {% endfor %}
  ```

## JavaScript
- Prefer inline `<script>` blocks in templates for page-specific JS.
- Use vanilla JS or Alpine.js patterns — no React/Vue.
- For AJAX calls use `fetch()` with CSRF token from cookie.

## Static Files
- Static assets served by WhiteNoise with cache-busting hashes.
- Reference static files: `{% load static %}` → `{% static 'charity/file.ext' %}`.
- App-level statics in `charity/static/charity/`.

## Email Templates
- Email templates live in `charity/templates/emails/`.
- Must be self-contained HTML (inline CSS, no external stylesheets).
- Include tracking pixel: `<img src="{{ tracking_url }}" width="1" height="1" />`.
- Include unsubscribe link in footer.
