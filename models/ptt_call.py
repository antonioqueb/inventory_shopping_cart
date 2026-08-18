# -*- coding: utf-8 -*-
"""Llamadas de voz 1 a 1 entre usuarios de la app STO Scanner.

A diferencia de los canales de radio (todos oyen a todos), aquí se crea una
sala improvisada entre dos personas. Mientras no haya push, el equipo llamado
se entera sondeando `poll_incoming` con la app abierta; cuando el push esté
en marcha, el sondeo pasa a ser solo la red de seguridad.
"""
import logging
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .ptt_channel import sign_livekit_token

_logger = logging.getLogger(__name__)

# Una llamada sin contestar deja de sonar pasado este tiempo.
RING_TIMEOUT_SECONDS = 45


class PttCall(models.Model):
    _name = 'sto.ptt.call'
    _description = 'Llamada de voz 1 a 1'
    _order = 'create_date desc'

    caller_id = fields.Many2one('res.users', string='Llama', required=True, ondelete='cascade', index=True)
    callee_id = fields.Many2one('res.users', string='Recibe', required=True, ondelete='cascade', index=True)
    room_name = fields.Char(string='Sala LiveKit', required=True, copy=False, index=True)
    state = fields.Selection(
        [
            ('ringing', 'Sonando'),
            ('active', 'En curso'),
            ('ended', 'Terminada'),
            ('rejected', 'Rechazada'),
            ('missed', 'Perdida'),
        ],
        string='Estado',
        default='ringing',
        required=True,
        index=True,
    )
    answered_at = fields.Datetime(string='Contestada')
    ended_at = fields.Datetime(string='Terminada')

    # ──────────────────────────────────────────────
    # Directorio
    # ──────────────────────────────────────────────

    @api.model
    def get_directory(self):
        """A quién puede llamar el usuario actual.

        Son los compañeros que comparten al menos un canal de radio con él:
        si el ERP ya los puso a hablar juntos, pueden llamarse.
        """
        me = self.env.user
        Channel = self.env['sto.ptt.channel'].sudo()
        peers = self.env['res.users']
        for channel in Channel.search([]):
            if channel._user_can_listen(me):
                peers |= channel._member_users()
        peers -= me

        online = self._online_user_ids()
        return [{
            'uid': user.id,
            'name': user.name,
            'login': user.login,
            'online': user.id in online,
        } for user in peers.sorted('name')]

    @api.model
    def _online_user_ids(self):
        """Quién dio señal de vida hace menos de dos minutos."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=2)
        presences = self.env['sto.ptt.presence'].sudo().search([
            ('last_seen', '>=', cutoff),
        ])
        return set(presences.mapped('user_id').ids)

    # ──────────────────────────────────────────────
    # Ciclo de vida de la llamada
    # ──────────────────────────────────────────────

    @api.model
    def start_call(self, callee_uid):
        """Crea la llamada y devuelve el token del que llama."""
        me = self.env.user
        callee = self.env['res.users'].sudo().browse(int(callee_uid))
        if not callee.exists() or not callee.active:
            raise UserError(_('Esa persona ya no está disponible.'))
        if callee.id == me.id:
            raise UserError(_('No puedes llamarte a ti mismo.'))

        allowed = {row['uid'] for row in self.get_directory()}
        if callee.id not in allowed:
            raise AccessError(_('No compartes ningún canal con %s.') % callee.name)

        # Colgamos cualquier llamada previa mía que quedara colgada.
        self._expire_stale()
        self.sudo().search([
            '|', ('caller_id', '=', me.id), ('callee_id', '=', me.id),
            ('state', 'in', ('ringing', 'active')),
        ]).write({'state': 'ended', 'ended_at': fields.Datetime.now()})

        call = self.sudo().create({
            'caller_id': me.id,
            'callee_id': callee.id,
            'room_name': 'call_%s' % uuid.uuid4().hex[:16],
            'state': 'ringing',
        })
        self._notify_incoming(call)

        credentials = sign_livekit_token(self.env, call.room_name, me, True)
        credentials.update({
            'call_id': call.id,
            'peer_name': callee.name,
            'peer_uid': callee.id,
        })
        return credentials

    @api.model
    def poll_incoming(self):
        """¿Me está llamando alguien? La app lo consulta cada pocos segundos."""
        self._expire_stale()
        call = self.sudo().search([
            ('callee_id', '=', self.env.user.id),
            ('state', '=', 'ringing'),
        ], limit=1, order='create_date desc')
        if not call:
            return False
        return {
            'call_id': call.id,
            'peer_name': call.caller_id.name,
            'peer_uid': call.caller_id.id,
        }

    @api.model
    def answer_call(self, call_id):
        """Contesta y devuelve el token de quien recibe."""
        call = self._get_mine(call_id)
        if call.callee_id != self.env.user:
            raise AccessError(_('Esta llamada no es para ti.'))
        if call.state != 'ringing':
            raise UserError(_('La llamada ya no está disponible.'))

        call.write({'state': 'active', 'answered_at': fields.Datetime.now()})
        credentials = sign_livekit_token(self.env, call.room_name, self.env.user, True)
        credentials.update({
            'call_id': call.id,
            'peer_name': call.caller_id.name,
            'peer_uid': call.caller_id.id,
        })
        return credentials

    @api.model
    def reject_call(self, call_id):
        call = self._get_mine(call_id)
        call.write({'state': 'rejected', 'ended_at': fields.Datetime.now()})
        return True

    @api.model
    def end_call(self, call_id):
        call = self._get_mine(call_id)
        if call.state in ('ringing', 'active'):
            call.write({'state': 'ended', 'ended_at': fields.Datetime.now()})
        return True

    @api.model
    def call_state(self, call_id):
        """Para que quien llama sepa si ya le contestaron o le colgaron."""
        call = self._get_mine(call_id)
        return call.state

    # ──────────────────────────────────────────────
    # Interno
    # ──────────────────────────────────────────────

    def _get_mine(self, call_id):
        call = self.sudo().browse(int(call_id))
        if not call.exists():
            raise UserError(_('La llamada ya no existe.'))
        if self.env.user not in (call.caller_id | call.callee_id):
            raise AccessError(_('Esta llamada no es tuya.'))
        return call

    @api.model
    def _expire_stale(self):
        """Una llamada que nadie contestó deja de sonar sola."""
        cutoff = fields.Datetime.subtract(
            fields.Datetime.now(), seconds=RING_TIMEOUT_SECONDS)
        stale = self.sudo().search([
            ('state', '=', 'ringing'),
            ('create_date', '<', cutoff),
        ])
        if stale:
            stale.write({'state': 'missed', 'ended_at': fields.Datetime.now()})

    def _notify_incoming(self, call):
        """Punto de enganche del push (fase 3).

        Hoy no hace nada: el equipo llamado se entera por sondeo. Cuando haya
        Firebase y certificado VoIP de Apple, aquí se dispara la notificación
        y la llamada suena con la app cerrada.
        """
        _logger.info(
            'PTT: llamada %s de %s a %s (sin push todavía)',
            call.id, call.caller_id.name, call.callee_id.name,
        )
