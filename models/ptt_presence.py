# -*- coding: utf-8 -*-
"""Quién está conectado a qué canal de radio, para el tablero de supervisión."""
from odoo import fields, models


class PttPresence(models.Model):
    _name = 'sto.ptt.presence'
    _description = 'Presencia en canal de radio'
    _order = 'last_seen desc'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', string='Usuario', required=True, ondelete='cascade', index=True)
    channel_id = fields.Many2one('sto.ptt.channel', string='Canal', ondelete='cascade', index=True)
    last_seen = fields.Datetime(string='Última señal', required=True, default=fields.Datetime.now)

    # Odoo 19: models.Constraint reemplaza a _sql_constraints (que ya no se aplica).
    _user_unique = models.Constraint(
        'unique(user_id)',
        'Solo se guarda la última presencia de cada usuario.',
    )

    def _touch(self, user, channel_id):
        """Un registro por usuario: se sobreescribe en cada aviso."""
        record = self.search([('user_id', '=', user.id)], limit=1)
        values = {
            'channel_id': channel_id or False,
            'last_seen': fields.Datetime.now(),
        }
        if record:
            record.write(values)
        else:
            self.create(dict(values, user_id=user.id))
