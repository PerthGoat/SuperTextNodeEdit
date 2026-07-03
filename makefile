all:
	rm SuperText.pyz; zip -r SuperText.pyz __main__.py LICENSE src

test:
	python -m unittest discover -s unittests -p "test*.py"
