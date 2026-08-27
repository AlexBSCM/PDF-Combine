---
name: Aura PDF
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3d4947'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#6d7a77'
  outline-variant: '#bcc9c6'
  surface-tint: '#006a61'
  primary: '#00685f'
  on-primary: '#ffffff'
  primary-container: '#008378'
  on-primary-container: '#f4fffc'
  inverse-primary: '#6bd8cb'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#595c5e'
  on-tertiary: '#ffffff'
  tertiary-container: '#727577'
  on-tertiary-container: '#fbfdff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#89f5e7'
  primary-fixed-dim: '#6bd8cb'
  on-primary-fixed: '#00201d'
  on-primary-fixed-variant: '#005049'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#e0e3e5'
  tertiary-fixed-dim: '#c4c7c9'
  on-tertiary-fixed: '#191c1e'
  on-tertiary-fixed-variant: '#444749'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 14px
  mono-md:
    fontFamily: jetbrainsMono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  container-margin: 24px
  gutter: 16px
---

## Brand & Style

The design system is built on a **Corporate / Modern** aesthetic, specifically tailored for a desktop utility application. The brand personality is rooted in reliability, efficiency, and clarity. It avoids unnecessary decorative elements in favor of a "tools-first" approach that minimizes cognitive load during complex file operations.

The target audience consists of professionals and administrative users who require a dependable tool for high-frequency document processing. The emotional response should be one of "effortless control"—where the interface feels stable, the hierarchy is obvious, and the "action" path is always clear through consistent use of color and whitespace. 

Key visual principles include:
- **Precision:** Perfect alignment and systematic spacing.
- **Clarity:** Distinct separation between file lists, configuration settings, and execution areas.
- **Quality:** High-grade typography and subtle depth to signify a premium, native-feeling desktop experience.

## Colors

The palette is anchored by a deep **Teal (#0D9488)**, chosen as the primary action color. Teal offers a professional alternative to standard blues, feeling both modern and grounded. 

- **Primary:** Used for the main "Convert" action, primary buttons, and active states.
- **Secondary (Slate):** Used for headers, primary text, and iconography to provide high contrast.
- **Neutrals:** A scale of cool grays (Slate/Gray) is used for backgrounds, borders, and secondary text to maintain a clean, SaaS-like environment.
- **Status Colors:** Semantic colors for success, error, and warning are used sparingly to communicate file processing states and system alerts.

The default mode is **Light**, utilizing a tiered background system (White for cards/inputs, off-white for the main application shell) to create a subtle sense of depth without heavy shadows.

## Typography

This design system utilizes **Inter** for all UI elements to ensure maximum legibility and a contemporary technical feel. For developer logs or file paths, **JetBrains Mono** is introduced to provide a clear distinction between "Interface" and "Data."

- **Headlines:** Use SemiBold weight with slight negative letter-spacing for a "tight," professional appearance.
- **Body:** The standard size is 14px (body-md) for desktop density, allowing more information to be visible without crowding.
- **Labels:** Small caps or medium-weight labels are used for form field headers and category titles to create a clear visual hierarchy against the body text.
- **Line Heights:** Generous line heights are maintained to ensure readability, especially in multi-line file lists or log outputs.

## Layout & Spacing

The layout follows a **structured grid** optimized for a desktop application window. It utilizes a logical grouping of components into functional zones (File Management, Configuration, Execution).

- **Spacing Rhythm:** Based on a 4px baseline. All margins and paddings must be multiples of 4.
- **Padding:** 16px (md) is the default padding for containers and cards to ensure the "generous whitespace" requested.
- **Functional Grouping:** Use 24px (lg) spacing to separate major sections (e.g., separating the file list from the output settings).
- **Alignment:** All inputs and buttons must align to a consistent vertical axis to maintain a professional, "SaaS" look.
- **Desktop Window:** The layout is designed for a minimum width of 1024px. On larger screens, the side margins expand while the main content area reaches a max-width of 1200px to maintain readability.

## Elevation & Depth

This design system uses **Tonal Layers** and **Low-Contrast Outlines** rather than heavy shadows to signify hierarchy. This keeps the interface feeling "light" and modern.

- **Level 0 (Base):** Background of the application window (#F8FAFC).
- **Level 1 (Containers):** Cards, file lists, and main work areas are White (#FFFFFF) with a soft 1px border (#E2E8F0).
- **Level 2 (Interactive):** Hover states and active inputs use a very subtle ambient shadow (4px blur, 2% opacity) to suggest clickability.
- **Depth Cues:** Active states for buttons and inputs use the Primary color or a slightly darker border; they do not "lift" off the page but rather "highlight" in place.

## Shapes

The shape language is consistently **Rounded**, utilizing an 8px (0.5rem) radius for standard components like buttons and input fields.

- **Standard (8px):** Buttons, Text Fields, Checkboxes.
- **Large (16px):** Main content cards and the "Drop Zone" for files.
- **Small (4px):** Tooltips and small status tags.

These rounded corners soften the technical nature of a PDF converter, making the application feel more approachable and user-friendly.

## Components

### Buttons
- **Primary:** Solid Teal (#0D9488) with white text. Reserved for the "Convert" or "Start" action.
- **Secondary:** White background with Slate (#475569) border and text. Used for "Add File," "Browse," etc.
- **Ghost:** No background/border. Used for low-priority actions like "Clear Log."

### Input Fields & Selects
- 8px rounded corners with a 1px border (#CBD5E1). 
- Active state uses a 2px Teal border. 
- Labels are positioned above the field in `label-md` style.

### File List
- Items are displayed in a clean list with 12px vertical padding. 
- Alternating row highlights or a subtle border between items.
- Include a "File Type" icon and a "Remove" button on hover.

### Progress Bar
- A thin (8px height) bar with a rounded Teal track.
- Used to show conversion status without obstructing other controls.

### Cards
- Used to group related settings (e.g., "Output Quality," "Page Settings").
- White background, 1px Slate-200 border, 16px internal padding.

### Drop Zone
- A large, dashed-border area within the file list container. 
- Uses a slightly tinted teal background (#F0FDFA) to encourage user interaction.