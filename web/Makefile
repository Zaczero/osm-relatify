.PHONY: update bundle version

update:
	docker push $$(docker load < $$(nix-build --no-out-link) | sed -En 's/Loaded image: (\S+)/\1/p')

bundle:
# menu.js
	HASH=$$(esbuild static/js/menu.js --bundle --minify | sha256sum | head -c8 ; echo '') && \
	esbuild static/js/menu.js --bundle --minify --sourcemap --charset=utf8 --outfile=static/js/menu.$$HASH.js && \
	find templates -type f -exec sed -i 's|src="/static/js/menu.js" type="module"|src="/static/js/menu.'$$HASH'.js"|g' {} \;

# style.css
	HASH=$$(esbuild static/css/style.css --bundle --minify | sha256sum | head -c8 ; echo '') && \
	esbuild static/css/style.css --bundle --minify --sourcemap --charset=utf8 --outfile=static/css/style.$$HASH.css && \
	find templates -type f -exec sed -i 's|href="/static/css/style.css"|href="/static/css/style.'$$HASH'.css"|g' {} \;

version:
	sed -i -r "s|VERSION = '([0-9.]+)'|VERSION = '\1.$$(date +%y%m%d)'|g" config.py
