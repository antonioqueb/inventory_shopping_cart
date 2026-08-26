# -*- coding: utf-8 -*-
"""Canales de voz push-to-talk para la app STO Scanner.

El API secret de LiveKit vive SOLO aquí, en parámetros del sistema. Si la app
firmara sus propios tokens, cualquiera con el APK podría extraer el secreto y
entrar a cualquier canal. Por eso el ERP revalida la membresía y firma un JWT
de corta vigencia en cada petición.
"""
import logging
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

try:
    import jwt
except ImportError:  # pragma: no cover
    jwt = None
    _logger.warning("PyJWT no está instalado: la radio push-to-talk no podrá emitir tokens")


class PttChannel(models.Model):
    _name = 'sto.ptt.channel'
    _description = 'Canal de voz push-to-talk'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    room_name = fields.Char(
        string='Sala LiveKit',
        required=True,
        copy=False,
        help='Identificador de la sala en LiveKit. Sin espacios ni acentos.',
    )
    description = fields.Text(string='Descripción')
    active = fields.Boolean(string='Activo', default=True)
    is_priority = fields.Boolean(
        string='Prioritario',
        help='Puede interrumpir el turno de palabra de los demás.',
    )

    listener_group_ids = fields.Many2many(
        'res.groups',
        'sto_ptt_channel_listener_group_rel',
        'channel_id', 'group_id',
        string='Grupos que escuchan',
    )
    talker_group_ids = fields.Many2many(
        'res.groups',
        'sto_ptt_channel_talker_group_rel',
        'channel_id', 'group_id',
        string='Grupos que hablan',
        help='Quien no esté aquí entra en modo solo escucha.',
    )
    member_ids = fields.Many2many(
        'res.users',
        'sto_ptt_channel_user_rel',
        'channel_id', 'user_id',
        string='Usuarios que escuchan',
        help='Asignación directa por usuario (no requiere grupo).',
    )
    talker_user_ids = fields.Many2many(
        'res.users',
        'sto_ptt_channel_talker_user_rel',
        'channel_id', 'user_id',
        string='Usuarios que hablan',
        help='Asignación directa por usuario: pueden hablar y escuchar '
             'aunque no estén en ningún grupo.',
    )

    member_count = fields.Integer(string='Miembros', compute='_compute_member_count')
    online_count = fields.Integer(string='En línea', compute='_compute_online_count')

    # Odoo 19: models.Constraint reemplaza a _sql_constraints (que ya no se aplica).
    _room_name_unique = models.Constraint(
        'unique(room_name)',
        'Ya existe un canal con esa sala de LiveKit.',
    )

    # ──────────────────────────────────────────────
    # Cómputos
    # ──────────────────────────────────────────────

    @api.depends('listener_group_ids', 'member_ids', 'talker_user_ids')
    def _compute_member_count(self):
        for channel in self:
            channel.member_count = len(channel._member_users())

    def _compute_online_count(self):
        Presence = self.env['sto.ptt.presence'].sudo()
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=2)
        for channel in self:
            channel.online_count = Presence.search_count([
                ('channel_id', '=', channel.id),
                ('last_seen', '>=', cutoff),
            ])

    def _som_group_users(self, group):
        """Usuarios de un grupo, tolerante a Odoo 19: res.groups ya no tiene
        'users'; se resuelve por el campo que exista. all_user_ids va PRIMERO
        y se UNE con user_ids: solo user_ids omite a quienes reciben el grupo
        por IMPLICACIÓN de otro grupo."""
        Users = self.env['res.users']
        if not group:
            return Users
        users = Users
        for fname in ('all_user_ids', 'user_ids', 'users'):
            if fname in group._fields:
                users |= group[fname]
        if users:
            return users.filtered(lambda u: u.active and not u.share)
        for fname in ('all_group_ids', 'group_ids', 'groups_id'):
            if fname in Users._fields:
                return Users.search([
                    (fname, 'in', group.id), ('active', '=', True)])
        return Users

    def _som_user_groups(self, user):
        """Grupos del usuario, incluidos los heredados por implicación."""
        for fname in ('all_group_ids', 'group_ids', 'groups_id'):
            if fname in user._fields:
                return user[fname]
        return self.env['res.groups']

    def _member_users(self):
        """Usuarios con acceso al canal: directos (escucha o habla) o por grupo."""
        self.ensure_one()
        users = self.member_ids | self.talker_user_ids
        for group in self.listener_group_ids:
            users |= self._som_group_users(group)
        return users

    def _user_can_listen(self, user):
        self.ensure_one()
        # Quien puede hablar, escucha: la asignación directa de habla basta.
        if user in self.member_ids or user in self.talker_user_ids:
            return True
        return bool(self.listener_group_ids & self._som_user_groups(user))

    def _user_can_talk(self, user):
        self.ensure_one()
        if user in self.talker_user_ids:
            return True
        if not self._user_can_listen(user):
            return False
        return bool(self.talker_group_ids & self._som_user_groups(user))

    # ──────────────────────────────────────────────
    # API que consume la app móvil
    # ──────────────────────────────────────────────

    @api.model
    def get_my_channels(self):
        """Canales que el usuario actual tiene autorizados."""
        user = self.env.user
        channels = self.sudo().search([])
        result = []
        for channel in channels:
            if not channel._user_can_listen(user):
                continue
            result.append({
                'id': channel.id,
                'name': channel.name,
                'room_name': channel.room_name,
                'description': channel.description or False,
                'is_priority': channel.is_priority,
                'can_transmit': channel._user_can_talk(user),
                'member_count': channel.member_count,
            })
        return result

    @api.model
    def mint_token(self, channel_id):
        """Firma un JWT de LiveKit para el canal, si el usuario sigue teniendo acceso.

        Se revalida en cada llamada: sacar a alguien de un grupo le corta el
        acceso en cuanto caduque el token que tenga vigente.
        """
        if jwt is None:
            raise UserError(_('Falta la librería PyJWT en el servidor (pip install pyjwt).'))

        user = self.env.user
        channel = self.sudo().browse(int(channel_id))
        if not channel.exists():
            raise UserError(_('El canal de radio ya no existe.'))
        if not channel._user_can_listen(user):
            raise AccessError(_('No tienes acceso al canal %s.') % channel.name)

        return sign_livekit_token(
            self.env, channel.room_name, user, channel._user_can_talk(user)
        )

    @api.model
    def report_presence(self, channel_id):
        """Marca al usuario como presente en un canal. `False` al salir.

        Es informativo: nunca debe tumbar la conexión de voz de la app.
        """
        try:
            self.env['sto.ptt.presence'].sudo()._touch(
                self.env.user, int(channel_id) if channel_id else False
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning('PTT: no se pudo registrar la presencia: %s', exc)
        return True


def sign_livekit_token(env, room_name, user, can_publish):
    """Firma un JWT de LiveKit. Único punto donde se toca el API secret.

    Lo usan tanto los canales de radio como las llamadas 1 a 1: si algún día
    cambia el formato del token, cambia aquí y en ningún otro sitio.
    """
    if jwt is None:
        raise UserError(_('Falta la librería PyJWT en el servidor (pip install pyjwt).'))

    params = env['ir.config_parameter'].sudo()
    server_url = params.get_param('sto_ptt.livekit_url')
    api_key = params.get_param('sto_ptt.livekit_api_key')
    api_secret = params.get_param('sto_ptt.livekit_api_secret')
    if not (server_url and api_key and api_secret):
        raise UserError(_(
            'La radio no está configurada. Faltan los parámetros del sistema '
            'sto_ptt.livekit_url, sto_ptt.livekit_api_key y sto_ptt.livekit_api_secret.'
        ))

    ttl_hours = int(params.get_param('sto_ptt.token_ttl_hours', 6))
    now = int(time.time())
    identity = 'uid:%s' % user.id

    payload = {
        'iss': api_key,
        'sub': identity,
        'nbf': now,
        'exp': now + ttl_hours * 3600,
        'name': user.name,
        'video': {
            'room': room_name,
            'roomJoin': True,
            # El "solo escucha" se aplica aquí: LiveKit rechaza la publicación
            # de audio en el servidor, no en la app.
            'canPublish': can_publish,
            'canSubscribe': True,
            'canPublishData': True,
        },
    }
    token = jwt.encode(payload, api_secret, algorithm='HS256')
    if isinstance(token, bytes):  # PyJWT < 2.0
        token = token.decode('utf-8')

    return {
        'server_url': server_url,
        'token': token,
        'identity': identity,
        'expires_at': fields.Datetime.to_string(
            fields.Datetime.add(fields.Datetime.now(), hours=ttl_hours)
        ),
    }
