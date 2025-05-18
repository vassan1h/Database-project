# Metabolic Model Database Web App

This is a Flask-based web application for uploading, querying, and visualizing gap-filled genome-scale metabolic models (GEMs), built as part of a database project for storing and managing metabolic reconstruction data in MariaDB. The app is to be used exclusively within SegreLab and findings are yet to be published.


## 🔍 Features

- Upload `.xml` and `.tsv` GEM files with metadata (growth media, algorithms, etc.)
- Search models by media and filter by growth outcome
- View/download associated files (growth/biomass data)
- API access for listing and submitting models
- Charge-based metabolite visualization with interactive charts
- Modular interface with Tailwind CSS and Chart.js
- Organized downloads via secure routes
- MariaDB integration with reconnect logic and transaction handling

---

## 🖼️ Frontend Templates Summary

All templates are written in **Jinja2** and styled with **Tailwind CSS** and **Inter** font.

### `index.html`
- Unified landing page with:
  - Model upload form
  - Search form (AJAX-enhanced)
  - Table display of results (latest or filtered)
  - Model metadata + file download links
  - Optional metadata: media, gapfill algorithm, annotation tool, growth data
  - Growth outcome filter toggle (`All`, `Growth`, `No Growth`)
  - Real-time upload status display

### `functionality.html`
- Interactive metabolite charge visualizer:
  - Upload `.xml`, `.csv`, or `.tsv` with `name` and `charge` fields
  - Plots full charge distribution and top 30 absolute charges
  - Downloads available as **JPEG** or **PDF**
  - All parsing and rendering performed in-browser (Chart.js + jsPDF)

### `about.html`
- Overview of the project and its purpose
- Describes tools used (Model SEED, RASTtk, etc.)
- Built for accessible model sharing across the lab

### `linked_databases.html` (placeholder)
- Optional page to link external databases (e.g., BiGG, KBase, KEGG)

### `help.html`
- Placeholder route for user guides or FAQ

### Shared Layout
- Navbar included via `{% include 'navbar.html' %}`
- Footer credits the developers and advisor, with lab contact

---

## Tech Stack:

- **Backend**: Python 3.x,  MariaDB
- **Frontend**: HTML (Jinja2 templates), Bootstrap, Flask, Flask-CORS
- **Database**: MariaDB (SQL schema includes `gapfill_models`, `metabolic_reactions`, `gap_filling_results`, `experimental_conditions`)
- **APIs**: GoogleAPIs
- **Deployment**: Cluster-ready (e.g., SCC), with file system persistence, there is also a network to COMETS, KBASE gapfill algorithm -> but it's private and yet to be deployed for publication. 

---

***Contributors:***
Aravind Panicker, Benjamin Pfeiffer, Nicolas Petrunich, Vassanth Mathan, Nicholas White.
For internal use by the Segrè Lab, Boston University