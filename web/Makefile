.PHONY update

update:
	docker run --privileged --rm tonistiigi/binfmt --install all
	docker buildx build --platform linux/amd64 -t docker.monicz.pl/osm-relatify --push .
