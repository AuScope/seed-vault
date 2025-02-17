Create autodocs from docstring:

`poetry run sphinx-apidoc -o docs/modules ../seed_vault`

Create Docs:

```
cd docs
poetry run make clean
poetry run make html
```
