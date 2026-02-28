# Contributing to JobPilotAI

Thank you for considering contributing to JobPilotAI! We welcome contributions from the community.

## Development Setup

### Prerequisites
- Python 3.11+
- Git

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/jobpilotai/jobpilotai.git
   cd JobPilotAI
   ```

2. **Run the setup script**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Activate the virtual environment**
   ```bash
   source venv/bin/activate
   ```

4. **Install development dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

## Code Style

We follow PEP 8 standards with these guidelines:

- **Line length**: Maximum 120 characters
- **Type hints**: Encouraged for all functions
- **Formatting**: Use consistent indentation (4 spaces)
- **Imports**: Organize using standard, third-party, local order

Example:
```python
from typing import Optional, List

def process_job(job_id: str, apply: bool = False) -> Optional[dict]:
    """Process job data with type hints and clear documentation."""
    return None
```

## Testing & Quality Checks

Run these commands before submitting a PR:

```bash
make lint       # Run linters (flake8)
make security   # Run security checks (bandit)
make test       # Run test suite (if available)
make clean      # Clean generated files
```

## Pull Request Process

1. **Fork the repository** and create a feature branch
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and commit with descriptive messages
   ```bash
   git commit -m "Add feature: description of what you changed"
   ```

3. **Run quality checks**
   ```bash
   make lint
   make security
   ```

4. **Push to your fork**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Submit a Pull Request** with:
   - Clear title describing the change
   - Description of what was changed and why
   - Reference to any related issues
   - Evidence that tests pass

## Security

**Important**: Do not report security vulnerabilities as public GitHub issues.

See [SECURITY.md](SECURITY.md) for responsible disclosure guidelines.

## Questions?

Open a GitHub discussion or issue with the `question` label for help getting started.

Thank you for contributing!
