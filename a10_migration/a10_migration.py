# Copyright 2018 Rackspace, US Inc.
# Copyright 2020 A10 Networks, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import datetime
import sys

from oslo_config import cfg
from oslo_db.sqlalchemy import enginefacade
import oslo_i18n as i18n
from oslo_log import log as logging

_translators = i18n.TranslatorFactory(domain='a10_migration')

# The primary translation function using the well-known name "_"
_ = _translators.primary

CONF = cfg.CONF

cli_opts = [
    cfg.BoolOpt('all', default=False,
                help='Migrate all Thunders'),
    cfg.StrOpt('device_name',
               help='Migrate the Thunder with this name'),
    cfg.StrOpt('project_id',
               help='Migrate the Thunder bound to this tenant/project'),
]

migration_opts = [
    cfg.BoolOpt('delete_after_migration', default=True,
                help='Delete the load balancer records from neutron-lbaas'
                     ' after migration'),
    cfg.BoolOpt('trial_run', default=False,
                help='Run without making changes.'),
    cfg.StrOpt('octavia_account_id', required=True,
               help='The keystone account ID Octavia is running under.'),
    cfg.StrOpt('a10_nlbaas_db_connection',
               required=True,
               help='The a10 nlbaas database connection string'),
    cfg.StrOpt('a10_oct_connection',
               required=True,
               help='The a10 octavia database connection string'),
    cfg.StrOpt('a10_config_path',
               required=True,
               help='Path to config.py file used by the A10 networks lbaas driver'),
]

cfg.CONF.register_cli_opts(cli_opts)
cfg.CONF.register_opts(migration_opts, group='migration')


def main():
    if len(sys.argv) < 1:
        print("Error: Config files must be specified.")
        print("a10_migration --config-file <filename>")
    logging.register_options(cfg.CONF)
    cfg.CONF(args=sys.argv[1:],
             project='a10_migration',
             version='a10_migration 1.0')
    logging.set_defaults()
    logging.setup(cfg.CONF, 'a10_migration')
    LOG = logging.getLogger('a10_migration')
    CONF.log_opt_values(LOG, logging.DEBUG)

    import pdb; pdb.set_trace()

    if not CONF.all and not CONF.device_name and not CONF.project_id:
        print('Error: One of --all, --lb_id, or --project_id must be specified.')
        return 1

    if ((CONF.all and (CONF.device_name or CONF.project_id)) or
            (CONF.device_name and CONF.project_id)):
        print('Error: Only one of --all, --device_name, or --project_id allowed.')
        return 1
    
    nlbaas_ctx_manager = enginefacade.transaction_context()
    nlbaas_ctx_manager.configure(connection=CONF.migration.a10_nlbaas_db_connection)
    nlbaas_session_maker = nlbaas_ctx_manager.writer.get_sessionmaker()

    octavia_context_manager = enginefacade.transaction_context()
    octavia_context_manager.configure(
        connection=CONF.migration.a10_oct_connection)
    o_session_maker = octavia_context_manager.writer.get_sessionmaker()

    LOG.info('Starting migration.')

    nlbaas_session = nlbaas_session_maker(autocommit=True)
    device_info_map = {}

    if CONF.device_name:
        tenant_id = nlbaas_session.execute(
            "SELECT tenant_id FROM neutron.a10_tenant_bindings WHERE "
            "device_name = :device_name; ",
            {"device_name": CONF.device_name})
        device_info_map[CONF.device_name] = CONF.device_name
    elif CONF.project_id:
        device_name = nlbaas_session.execute(
            "SELECT device_name FROM neutron.a10_tenant_bindings WHERE "
            "tenant_id = :tenant_id ;", {"tenant_id": CONF.project_id})
        device_info_map[device_name] = CONF.project_id
    else:
        tenant_bindings = nlbaas_session.execute(
            "SELECT tenant_id, device_name FROM neutron.a10_tenant_bindings;").fetchall()
        tenant_bindings = dict(tenant_bindings)
    
    a10_config = A10Config(config_dir=CONF.a10_config_path, provider="a10networks")

    failure_count = 0
    for device_name in device_info_map.keys():
        device_info_map[device_name].update(a10_config.get_device(device_name))

    if failure_count:
        sys.exit(1)


if __name__ == "__main__":
    main()