# Project Structure

```text
servicios-financieros/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── controllers/
│   │   ├── __init__.py
│   │   ├── chat_controller.py
│   │   ├── fintech_controller.py
│   │   └── whatsapp_controller.py
│   └── models/
│       ├── __init__.py
│       ├── assistant.py
│       ├── database.py
│       ├── llama_stack_store.py
│       ├── safety.py
│       ├── schemas.py
│       └── whatsapp.py
├── code/
│   └── features/
│       └── 20261020-fintech-omnichannel-assistant/
├── docs/
│   ├── api-contracts.md
│   ├── architecture.md
│   ├── base-standards.md
│   ├── project-structure.md
│   └── ui-ux-standards.md
├── tests/
│   └── test_app_integration.py
├── web/
│   ├── app.js
│   ├── index.html
│   └── styles.css
├── .env.example
├── CHANGELOG.md
├── Dockerfile
├── knowledge_base.json
├── README.md
├── requirements-dev.txt
└── requirements.txt
```
