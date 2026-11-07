// LSM is a single-user Controller-authenticated application. Only its JWT
// session and the legacy OIDC logout compatibility helpers remain.
const jwtLogin = require('./jwtStrategy');
const { getOpenIdConfig, getOpenIdEmail } = require('./openidStrategy');

module.exports = { jwtLogin, getOpenIdConfig, getOpenIdEmail };
