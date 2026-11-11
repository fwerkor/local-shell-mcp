// Bound test concurrency independently of the Controller's CPU count.
module.exports = { maxWorkers: process.env.JEST_MAX_WORKERS || 2 };
