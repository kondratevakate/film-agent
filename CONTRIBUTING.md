# Contributing to Film-Agent

Thank you for your interest in contributing to Film-Agent! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.11+
- pip or uv for package management

### Development Setup

1. Clone the repository:
```bash
git clone https://github.com/your-org/film-agent.git
cd film-agent
```

2. Install in development mode:
```bash
pip install -e ".[dev]"
```

3. Copy environment template:
```bash
cp .env.example .env
# Edit .env with your API keys
```

## Development Workflow

### Code Style

- We use **Black** for code formatting
- We use **isort** for import sorting
- We use **mypy** for type checking

Run formatters before committing:
```bash
black src/ tests/
isort src/ tests/
mypy src/
```

### Testing

Run tests with pytest:
```bash
pytest tests/
```

Run with coverage:
```bash
pytest --cov=film_agent tests/
```

### Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linters
5. Commit with a descriptive message
6. Push to your fork
7. Open a Pull Request

### Commit Messages

Follow conventional commits:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Adding/updating tests
- `chore:` Maintenance tasks

## Architecture Overview

### Core Modules (`src/film_agent/core/`)

- `AuthorIntent` - Immutable narrative context
- `MetaphorTranslator` - Converts metaphors to visual descriptions
- `StyleEnforcer` - Validates photorealistic style
- `ValidationLoop` - Orchestrates all validators

### Pipeline (`src/film_agent/`)

- `state_machine/` - Orchestration and state management
- `gates/` - Quality gates (gate0-4, story_qa, cinematography_qa)
- `providers/` - External API adapters
- `schemas/` - Pydantic data models

### Configuration

- `configs/` - Project-specific configurations
- `world.yaml` - Room/character definitions
- `shots.yaml` - Shot list
- `author_intent.yaml` - Narrative context

## Reporting Issues

When reporting bugs, please include:
- Python version
- OS and version
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## Questions?

Open an issue or reach out to the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
