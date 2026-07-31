all:
	rm -f SuperText.pyz; zip -r SuperText.pyz __main__.py LICENSE src

test:
	python3 -m unittest discover -s unittests -p "test*.py"
