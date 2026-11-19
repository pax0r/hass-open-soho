# OpenSOHO

1. Set `shared_secret` in the add-on configuration to a random value with at least 32 characters. Configure the same value on each router.
2. Enable **Show in sidebar** on the add-on page. Start OpenSOHO and open its panel in the Home Assistant sidebar using an administrator account.
3. In OpenWrt set the OpenWISP server URL to `http://<LAN-IP-of-HA>:8090`, with no trailing slash. The network setting of the add-on controls the published port.
4. New devices are registered with configuration delivery disabled by default. Review their settings before enabling delivery, especially on gateways running PPPoE and DHCP.

The Home Assistant backup should include OpenSOHO. The Supervisor stops the add-on to snapshot the database and restarts it afterwards. Keep backups private because they contain router credentials and configuration. For diagnostics, restore steps and the Ingress compatibility requirements, see the repository documentation.

[Repository documentation](https://github.com/pax0r/hass-open-soho)
