/** 为插件逻辑测试注册公开子入口解析器 */
import { register } from "node:module";
register("./sdk-loader.mjs", import.meta.url);
