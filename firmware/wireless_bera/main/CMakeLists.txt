idf_component_register(
    SRCS
        "main.c"
        "i2c_bus.c"
        "pgia.c"
        "status_led.c"
        "battery.c"
        "tps65132.c"
        "tac5212.c"
        "audio.c"
        "net.c"
        "web.c"
        "console.c"
    INCLUDE_DIRS "."
)

# The web UI is a single HTML file. Compress it at build time and link the
# gzip stream straight into the binary - the server sets Content-Encoding.
set(WEBUI_SRC "${CMAKE_CURRENT_SOURCE_DIR}/www/index.html")
set(WEBUI_GZ  "${CMAKE_CURRENT_BINARY_DIR}/index.html.gz")

add_custom_command(
    OUTPUT "${WEBUI_GZ}"
    COMMAND gzip -9 -n -c "${WEBUI_SRC}" > "${WEBUI_GZ}"
    DEPENDS "${WEBUI_SRC}"
    COMMENT "Compressing web UI"
    VERBATIM
)
add_custom_target(webui_gz DEPENDS "${WEBUI_GZ}")
add_dependencies(${COMPONENT_LIB} webui_gz)

target_add_binary_data(${COMPONENT_LIB} "${WEBUI_GZ}" BINARY)
