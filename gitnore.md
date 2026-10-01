# Git ignore reference

The active ignore file is `.gitignore`.

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Node / frontend
node_modules/
dist/
build/

# Runtime / secrets
.env
.env.*
*.key
*.pem
*.crt
secrets/
runtime/
logs/

# Database / backup artifacts
*.sql.gz
*.dump
*.backup

# OS / IDE
.DS_Store
.idea/
.vscode/

# Temporary files
*.tmp
*.swp
*.bak
```
