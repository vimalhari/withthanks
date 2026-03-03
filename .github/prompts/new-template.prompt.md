---
description: "Generate a new Django template page extending the dashboard layout"
---

# New Dashboard Template

Create a Django template page following WithThanks UI conventions.

## Requirements
- Extend `base_dashboard.html` for authenticated pages.
- Use Tailwind CSS utility classes exclusively — no custom CSS.
- Use `{% url 'name' %}` for all links.
- Include `{% csrf_token %}` in all forms.
- Use Django messages framework for flash notifications.
- Load custom template tags: `{% load charity_extras %}`.

## Template Structure
```html
{% extends "base_dashboard.html" %}
{% load static charity_extras %}

{% block title %}${1:Page Title} — WithThanks{% endblock %}

{% block content %}
<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <!-- Page header -->
    <div class="mb-8">
        <h1 class="text-2xl font-bold text-gray-900">${1}</h1>
        <p class="mt-1 text-sm text-gray-500">${2:Page description}</p>
    </div>

    <!-- Flash messages -->
    {% for message in messages %}
    <div class="mb-4 p-4 rounded-md {% if message.tags == 'error' %}bg-red-50 text-red-800{% elif message.tags == 'success' %}bg-green-50 text-green-800{% else %}bg-blue-50 text-blue-800{% endif %}">
        {{ message }}
    </div>
    {% endfor %}

    <!-- Main content -->
    <div class="bg-white rounded-lg shadow p-6">
        ${3:<!-- Content here -->}
    </div>
</div>
{% endblock %}
```

## Common Patterns

### Data Table
```html
<table class="min-w-full divide-y divide-gray-200">
    <thead class="bg-gray-50">
        <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Column</th>
        </tr>
    </thead>
    <tbody class="bg-white divide-y divide-gray-200">
        {% for item in items %}
        <tr>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{{ item.field }}</td>
        </tr>
        {% empty %}
        <tr>
            <td class="px-6 py-4 text-sm text-gray-500" colspan="99">No items found.</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

### Form
```html
<form method="post" class="space-y-6">
    {% csrf_token %}
    {% for field in form %}
    <div>
        <label for="{{ field.id_for_label }}" class="block text-sm font-medium text-gray-700">
            {{ field.label }}
        </label>
        {{ field }}
        {% if field.errors %}
        <p class="mt-1 text-sm text-red-600">{{ field.errors.0 }}</p>
        {% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md text-sm font-medium">
        Submit
    </button>
</form>
```
