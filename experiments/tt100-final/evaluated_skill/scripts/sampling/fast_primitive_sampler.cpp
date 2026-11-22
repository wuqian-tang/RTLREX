#include <algorithm>
#include <bitset>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <memory>
#include <utility>
#include <vector>

namespace {

constexpr size_t BATCH_BITS = 4096;

enum GateType { AND, OR, NAND, NOR, NOT, BUF, XOR, XNOR };

struct Port {
    std::string name;
    int width = 1;
};

struct Gate {
    GateType type;
    int out = -1;
    std::vector<int> ins;
};

struct Signal {
    std::string label;
    std::vector<int> bit_ids;
};

struct Expr {
    enum Kind { CONST_VALUE, SIGNAL_VALUE, CONCAT, REPLICATE, TERNARY, ADD, SUB, CAST_SIGNED, CAST_UNSIGNED } kind = CONST_VALUE;
    uint64_t value = 0;
    int width = 1;
    std::string signal;
    std::vector<std::unique_ptr<Expr>> args;
};

struct Assign {
    std::string lhs;
    std::unique_ptr<Expr> rhs;
};

struct Step {
    bool is_assign = false;
    size_t index = 0;
};

struct Netlist {
    std::vector<Port> inputs;
    std::vector<Port> outputs;
    std::vector<Gate> gates;
    std::vector<Assign> assigns;
    std::vector<Step> steps;
    std::unordered_map<std::string, int> wire_id;
    std::unordered_map<std::string, int> vector_width;
    std::vector<std::string> wire_names;
    std::vector<uint8_t> is_input_bit;
};

std::string trim(std::string s) {
    while (!s.empty() && std::isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t first = 0;
    while (first < s.size() && std::isspace(static_cast<unsigned char>(s[first]))) ++first;
    return s.substr(first);
}

std::vector<std::string> split(const std::string &s, char sep) {
    std::vector<std::string> out;
    std::string cur;
    std::stringstream ss(s);
    while (std::getline(ss, cur, sep)) {
        cur = trim(cur);
        if (!cur.empty()) out.push_back(cur);
    }
    return out;
}

std::vector<std::string> split_top_level(const std::string &s, char sep) {
    std::vector<std::string> out;
    std::string cur;
    int depth = 0;
    for (char c : s) {
        if (c == '(' || c == '{' || c == '[') ++depth;
        if (c == ')' || c == '}' || c == ']') --depth;
        if (c == sep && depth == 0) {
            cur = trim(cur);
            if (!cur.empty()) out.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    cur = trim(cur);
    if (!cur.empty()) out.push_back(cur);
    return out;
}

size_t find_top_level_char(const std::string &s, char target) {
    int depth = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        char c = s[i];
        if (c == '(' || c == '{' || c == '[') ++depth;
        else if (c == ')' || c == '}' || c == ']') --depth;
        else if (c == target && depth == 0) return i;
    }
    return std::string::npos;
}

size_t find_top_level_open_brace(const std::string &s) {
    int depth = 0;
    for (size_t i = 0; i < s.size(); ++i) {
        char c = s[i];
        if (c == '{') {
            if (depth == 0) return i;
            ++depth;
        } else if (c == '(' || c == '[') {
            ++depth;
        } else if (c == '}' || c == ')' || c == ']') {
            --depth;
        }
    }
    return std::string::npos;
}

std::string strip_outer_parens(std::string s) {
    s = trim(s);
    while (s.size() >= 2 && s.front() == '(' && s.back() == ')') {
        int depth = 0;
        bool wraps = true;
        for (size_t i = 0; i < s.size(); ++i) {
            if (s[i] == '(' || s[i] == '{' || s[i] == '[') ++depth;
            else if (s[i] == ')' || s[i] == '}' || s[i] == ']') --depth;
            if (depth == 0 && i + 1 < s.size()) {
                wraps = false;
                break;
            }
        }
        if (!wraps) break;
        s = trim(s.substr(1, s.size() - 2));
    }
    return s;
}

std::string read_file(const std::string &path) {
    std::ifstream fin(path);
    if (!fin) throw std::runtime_error("cannot open " + path);
    std::ostringstream ss;
    ss << fin.rdbuf();
    return ss.str();
}

int parse_width(const std::string &range_text) {
    if (range_text.empty()) return 1;
    static const std::regex num_re("(\\d+)");
    std::sregex_iterator it(range_text.begin(), range_text.end(), num_re), end;
    std::vector<int> nums;
    for (; it != end; ++it) nums.push_back(std::stoi((*it)[1].str()));
    if (nums.size() < 2) return 1;
    return std::abs(nums[0] - nums[1]) + 1;
}

bool parse_const_bit(const std::string &tok, int &value) {
    std::string s = trim(tok);
    if (s == "0" || s == "1") {
        value = s[0] - '0';
        return true;
    }
    if (s.size() >= 3 && s.find("'b") != std::string::npos) {
        char c = s.back();
        if (c == '0' || c == '1') {
            value = c - '0';
            return true;
        }
    }
    return false;
}

bool parse_const_value(const std::string &tok, uint64_t &value, int &width) {
    std::string s = trim(tok);
    static const std::regex based_re(R"(^(\d+)'([bBdDhH])([0-9a-fA-F_xXzZ]+)$)");
    std::smatch m;
    if (std::regex_match(s, m, based_re)) {
        width = std::stoi(m[1].str());
        char base = static_cast<char>(std::tolower(m[2].str()[0]));
        std::string digits = m[3].str();
        digits.erase(std::remove(digits.begin(), digits.end(), '_'), digits.end());
        for (char &c : digits) {
            if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') c = '0';
        }
        int radix = base == 'b' ? 2 : (base == 'h' ? 16 : 10);
        value = digits.empty() ? 0 : std::stoull(digits, nullptr, radix);
        if (width < 64) value &= (uint64_t(1) << width) - 1;
        return true;
    }
    static const std::regex plain_re(R"(^\d+$)");
    if (std::regex_match(s, plain_re)) {
        value = std::stoull(s, nullptr, 10);
        width = 64;
        return true;
    }
    return false;
}

int get_wire(Netlist &nl, const std::string &name) {
    auto it = nl.wire_id.find(name);
    if (it != nl.wire_id.end()) return it->second;
    int id = static_cast<int>(nl.wire_id.size());
    nl.wire_id[name] = id;
    nl.wire_names.push_back(name);
    nl.is_input_bit.push_back(0);
    return id;
}

void add_port_bits(Netlist &nl, const Port &p, bool is_input) {
    nl.vector_width[p.name] = p.width;
    if (p.width == 1) {
        int id = get_wire(nl, p.name);
        if (is_input) nl.is_input_bit[id] = 1;
        return;
    }
    for (int i = 0; i < p.width; ++i) {
        int id = get_wire(nl, p.name + "[" + std::to_string(i) + "]");
        if (is_input) nl.is_input_bit[id] = 1;
    }
}

void add_vector_bits(Netlist &nl, const std::string &name, int width) {
    nl.vector_width[name] = std::max(nl.vector_width[name], width);
    if (width == 1) {
        get_wire(nl, name);
        return;
    }
    for (int i = 0; i < width; ++i) {
        get_wire(nl, name + "[" + std::to_string(i) + "]");
    }
}

std::unique_ptr<Expr> parse_expr(const Netlist &nl, std::string text);

std::unique_ptr<Expr> make_expr(Expr::Kind kind) {
    auto expr = std::make_unique<Expr>();
    expr->kind = kind;
    return expr;
}

std::unique_ptr<Expr> parse_expr(const Netlist &nl, std::string text) {
    text = strip_outer_parens(text);

    for (const auto &cast : {std::pair<std::string, Expr::Kind>{"$signed", Expr::CAST_SIGNED},
                             std::pair<std::string, Expr::Kind>{"$unsigned", Expr::CAST_UNSIGNED}}) {
        const std::string &name = cast.first;
        if (text.rfind(name, 0) == 0) {
            std::string arg_text = trim(text.substr(name.size()));
            if (arg_text.size() >= 2 && arg_text.front() == '(' && arg_text.back() == ')') {
                auto expr = make_expr(cast.second);
                expr->args.push_back(parse_expr(nl, arg_text.substr(1, arg_text.size() - 2)));
                expr->width = expr->args[0]->width;
                return expr;
            }
        }
    }

    size_t qpos = find_top_level_char(text, '?');
    if (qpos != std::string::npos) {
        std::string tail = text.substr(qpos + 1);
        size_t cpos = find_top_level_char(tail, ':');
        if (cpos == std::string::npos) throw std::runtime_error("malformed ternary assign: " + text);
        auto expr = make_expr(Expr::TERNARY);
        expr->args.push_back(parse_expr(nl, text.substr(0, qpos)));
        expr->args.push_back(parse_expr(nl, tail.substr(0, cpos)));
        expr->args.push_back(parse_expr(nl, tail.substr(cpos + 1)));
        expr->width = std::max(expr->args[1]->width, expr->args[2]->width);
        return expr;
    }

    std::vector<std::string> add_parts = split_top_level(text, '+');
    if (add_parts.size() > 1) {
        auto expr = make_expr(Expr::ADD);
        for (const std::string &part : add_parts) {
            auto arg = parse_expr(nl, part);
            expr->width = std::max(expr->width, arg->width);
            expr->args.push_back(std::move(arg));
        }
        return expr;
    }

    std::vector<std::string> sub_parts = split_top_level(text, '-');
    if (sub_parts.size() > 1) {
        auto expr = make_expr(Expr::SUB);
        for (const std::string &part : sub_parts) {
            auto arg = parse_expr(nl, part);
            expr->width = std::max(expr->width, arg->width);
            expr->args.push_back(std::move(arg));
        }
        return expr;
    }

    if (text.size() >= 2 && text.front() == '{' && text.back() == '}') {
        std::string inner = trim(text.substr(1, text.size() - 2));
        size_t rep_open = find_top_level_open_brace(inner);
        if (rep_open != std::string::npos && inner.back() == '}') {
            uint64_t repeat_count = 0;
            int repeat_width = 1;
            if (parse_const_value(inner.substr(0, rep_open), repeat_count, repeat_width)) {
                auto arg = parse_expr(nl, inner.substr(rep_open + 1, inner.size() - rep_open - 2));
                auto expr = make_expr(Expr::REPLICATE);
                expr->value = repeat_count;
                uint64_t width = repeat_count * static_cast<uint64_t>(std::max(arg->width, 1));
                expr->width = width > 64 ? 64 : static_cast<int>(std::max<uint64_t>(width, 1));
                expr->args.push_back(std::move(arg));
                return expr;
            }
        }
        auto expr = make_expr(Expr::CONCAT);
        int width = 0;
        for (const std::string &part : split_top_level(inner, ',')) {
            auto arg = parse_expr(nl, part);
            width += arg->width;
            expr->args.push_back(std::move(arg));
        }
        expr->width = std::max(width, 1);
        return expr;
    }

    uint64_t value = 0;
    int width = 1;
    if (parse_const_value(text, value, width)) {
        auto expr = make_expr(Expr::CONST_VALUE);
        expr->value = value;
        expr->width = width;
        return expr;
    }

    auto expr = make_expr(Expr::SIGNAL_VALUE);
    expr->signal = text;
    auto width_it = nl.vector_width.find(text);
    expr->width = width_it == nl.vector_width.end() ? 1 : width_it->second;
    return expr;
}

void collect_expr_deps(const Netlist &nl, const Expr &expr, std::vector<int> &deps) {
    if (expr.kind == Expr::SIGNAL_VALUE) {
        if (expr.width == 1) {
            auto exact = nl.wire_id.find(expr.signal);
            if (exact != nl.wire_id.end()) deps.push_back(exact->second);
            return;
        }
        for (int i = 0; i < expr.width; ++i) {
            auto it = nl.wire_id.find(expr.signal + "[" + std::to_string(i) + "]");
            if (it != nl.wire_id.end()) deps.push_back(it->second);
        }
        return;
    }
    for (const auto &arg : expr.args) collect_expr_deps(nl, *arg, deps);
}

int lhs_width(const Netlist &nl, const std::string &lhs) {
    std::string name = trim(lhs);
    if (name.size() >= 2 && name.front() == '{' && name.back() == '}') {
        int width = 0;
        for (const std::string &part : split_top_level(name.substr(1, name.size() - 2), ',')) {
            width += lhs_width(nl, part);
        }
        return std::max(width, 1);
    }
    auto width_it = nl.vector_width.find(name);
    if (width_it != nl.vector_width.end()) return width_it->second;
    return 1;
}

void collect_lhs_bits(Netlist &nl, const std::string &lhs, std::vector<int> &ids) {
    std::string name = trim(lhs);
    if (name.size() >= 2 && name.front() == '{' && name.back() == '}') {
        std::vector<std::string> parts = split_top_level(name.substr(1, name.size() - 2), ',');
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) collect_lhs_bits(nl, *it, ids);
        return;
    }
    auto width_it = nl.vector_width.find(name);
    if (width_it == nl.vector_width.end()) {
        ids.push_back(get_wire(nl, name));
        return;
    }
    int width = width_it->second;
    if (width == 1) {
        ids.push_back(get_wire(nl, name));
        return;
    }
    for (int i = 0; i < width; ++i) ids.push_back(get_wire(nl, name + "[" + std::to_string(i) + "]"));
}

GateType parse_gate_type(const std::string &s) {
    if (s == "and") return AND;
    if (s == "or") return OR;
    if (s == "nand") return NAND;
    if (s == "nor") return NOR;
    if (s == "not") return NOT;
    if (s == "buf") return BUF;
    if (s == "xor") return XOR;
    if (s == "xnor") return XNOR;
    throw std::runtime_error("unknown gate type " + s);
}

Netlist parse_netlist(const std::string &path) {
    Netlist nl;
    std::string text = read_file(path);

    static const std::regex decl_re(R"(^\s*(input|output)\s*(?:signed|unsigned)?\s*(\[[^\]]+\])?\s*([^;]+);)", std::regex::multiline);
    for (std::sregex_iterator it(text.begin(), text.end(), decl_re), end; it != end; ++it) {
        std::string kind = (*it)[1].str();
        std::string range = (*it)[2].str();
        std::string names = (*it)[3].str();
        int width = parse_width(range);
        for (std::string name : split(names, ',')) {
            if (name.find('[') != std::string::npos) continue;
            Port p{name, width};
            if (kind == "input") {
                nl.inputs.push_back(p);
                add_port_bits(nl, p, true);
            } else {
                nl.outputs.push_back(p);
                add_port_bits(nl, p, false);
            }
        }
    }

    static const std::regex wire_decl_re(R"(^\s*wire\s*(?:signed|unsigned)?\s*(\[[^\]]+\])?\s*([^;]+);)", std::regex::multiline);
    for (std::sregex_iterator it(text.begin(), text.end(), wire_decl_re), end; it != end; ++it) {
        std::string range = (*it)[1].str();
        std::string names = (*it)[2].str();
        int width = parse_width(range);
        for (std::string name : split(names, ',')) {
            if (name.find('[') != std::string::npos) continue;
            add_vector_bits(nl, name, width);
        }
    }

    std::vector<Gate> raw_gates;
    static const std::regex gate_re(R"(^\s*(and|or|nand|nor|not|buf|xor|xnor)\s+\S+\((.*?)\);)", std::regex::multiline);
    for (std::sregex_iterator it(text.begin(), text.end(), gate_re), end; it != end; ++it) {
        std::vector<std::string> args = split((*it)[2].str(), ',');
        if (args.size() < 2) throw std::runtime_error("malformed gate");
        Gate g;
        g.type = parse_gate_type((*it)[1].str());
        g.out = get_wire(nl, args[0]);
        for (size_t i = 1; i < args.size(); ++i) {
            int c = 0;
            if (parse_const_bit(args[i], c)) {
                g.ins.push_back(c ? -2 : -1);
            } else {
                g.ins.push_back(get_wire(nl, args[i]));
            }
        }
        raw_gates.push_back(std::move(g));
    }

    static const std::regex assign_re(R"(^\s*assign\s+([^=]+?)\s*=\s*([\s\S]*?);)", std::regex::multiline);
    for (std::sregex_iterator it(text.begin(), text.end(), assign_re), end; it != end; ++it) {
        std::string lhs = trim((*it)[1].str());
        std::string rhs_text = (*it)[2].str();
        Assign assign;
        assign.lhs = lhs;
        assign.rhs = parse_expr(nl, rhs_text);
        int lhs_bits = lhs_width(nl, lhs);
        if (assign.rhs->kind == Expr::CAST_SIGNED || assign.rhs->kind == Expr::CAST_UNSIGNED) {
            assign.rhs->width = std::max(assign.rhs->width, lhs_bits);
        }
        if (lhs.find('{') == std::string::npos && nl.vector_width.find(lhs) == nl.vector_width.end() && lhs.find('[') == std::string::npos) {
            add_vector_bits(nl, lhs, assign.rhs->width);
        }
        std::vector<int> lhs_ids;
        collect_lhs_bits(nl, lhs, lhs_ids);
        nl.assigns.push_back(std::move(assign));
    }

    std::vector<uint8_t> known(nl.wire_id.size(), 0);
    for (size_t i = 0; i < nl.is_input_bit.size(); ++i) {
        if (nl.is_input_bit[i]) known[i] = 1;
    }
    std::vector<uint8_t> used_gates(raw_gates.size(), 0);
    std::vector<uint8_t> used_assigns(nl.assigns.size(), 0);
    nl.gates.reserve(raw_gates.size());
    size_t remaining = raw_gates.size() + nl.assigns.size();
    while (remaining) {
        bool progressed = false;
        for (size_t i = 0; i < raw_gates.size(); ++i) {
            if (used_gates[i]) continue;
            bool ready = true;
            for (int in : raw_gates[i].ins) {
                if (in >= 0 && !known[in]) {
                    ready = false;
                    break;
                }
            }
            if (!ready) continue;
            used_gates[i] = 1;
            known[raw_gates[i].out] = 1;
            nl.gates.push_back(raw_gates[i]);
            nl.steps.push_back(Step{false, nl.gates.size() - 1});
            --remaining;
            progressed = true;
        }
        for (size_t i = 0; i < nl.assigns.size(); ++i) {
            if (used_assigns[i]) continue;
            std::vector<int> deps;
            collect_expr_deps(nl, *nl.assigns[i].rhs, deps);
            bool ready = true;
            for (int dep : deps) {
                if (dep >= 0 && !known[dep]) {
                    ready = false;
                    break;
                }
            }
            if (!ready) continue;
            std::vector<int> lhs_ids;
            collect_lhs_bits(nl, nl.assigns[i].lhs, lhs_ids);
            used_assigns[i] = 1;
            for (int id : lhs_ids) known[id] = 1;
            nl.steps.push_back(Step{true, i});
            --remaining;
            progressed = true;
        }
        if (!progressed) throw std::runtime_error("cannot topologically order gates/assigns");
    }
    return nl;
}

uint64_t parse_u64(const std::string &s) {
    size_t pos = 0;
    uint64_t value = std::stoull(s, &pos, 0);
    if (pos != s.size()) throw std::runtime_error("bad integer: " + s);
    return value;
}

void set_port(std::vector<uint8_t> &bits, const Netlist &nl, const Port &p, uint64_t value) {
    if (p.width == 1) {
        bits.at(nl.wire_id.at(p.name)) = value & 1;
        return;
    }
    for (int i = 0; i < p.width; ++i) {
        bits.at(nl.wire_id.at(p.name + "[" + std::to_string(i) + "]")) = (value >> i) & 1;
    }
}

uint64_t get_port(const std::vector<uint8_t> &bits, const Netlist &nl, const Port &p) {
    if (p.width == 1) return bits.at(nl.wire_id.at(p.name)) & 1;
    uint64_t value = 0;
    for (int i = 0; i < p.width; ++i) {
        value |= uint64_t(bits.at(nl.wire_id.at(p.name + "[" + std::to_string(i) + "]")) & 1) << i;
    }
    return value;
}

Signal resolve_signal(const Netlist &nl, const std::string &name) {
    auto exact = nl.wire_id.find(name);
    if (exact != nl.wire_id.end()) return Signal{name, {exact->second}};

    std::vector<int> ids;
    for (int i = 0;; ++i) {
        auto it = nl.wire_id.find(name + "[" + std::to_string(i) + "]");
        if (it == nl.wire_id.end()) break;
        ids.push_back(it->second);
    }
    if (!ids.empty()) return Signal{name, ids};

    throw std::runtime_error("unknown signal: " + name);
}

std::vector<Signal> default_output_signals(const Netlist &nl) {
    std::vector<Signal> signals;
    signals.reserve(nl.outputs.size());
    for (const Port &p : nl.outputs) {
        Signal sig;
        sig.label = p.name;
        if (p.width == 1) {
            sig.bit_ids.push_back(nl.wire_id.at(p.name));
        } else {
            for (int i = 0; i < p.width; ++i) {
                sig.bit_ids.push_back(nl.wire_id.at(p.name + "[" + std::to_string(i) + "]"));
            }
        }
        signals.push_back(std::move(sig));
    }
    return signals;
}

std::vector<Signal> all_wire_signals(const Netlist &nl) {
    std::vector<Signal> signals;
    signals.reserve(nl.wire_names.size());
    for (size_t i = 0; i < nl.wire_names.size(); ++i) {
        signals.push_back(Signal{nl.wire_names[i], {static_cast<int>(i)}});
    }
    return signals;
}

std::vector<std::string> read_signal_file(const std::string &path) {
    std::ifstream fin(path);
    if (!fin) throw std::runtime_error("cannot open signal file " + path);
    std::vector<std::string> names;
    std::string line;
    while (std::getline(fin, line)) {
        line = trim(line);
        if (!line.empty()) names.push_back(line);
    }
    return names;
}

uint8_t wire_value(const std::vector<uint8_t> &bits, int id) {
    if (id == -1) return 0;
    if (id == -2) return 1;
    return bits[id] & 1;
}

std::bitset<BATCH_BITS> batch_const(int id) {
    if (id == -1) return std::bitset<BATCH_BITS>();
    if (id == -2) return ~std::bitset<BATCH_BITS>();
    throw std::runtime_error("bad const id");
}

const std::bitset<BATCH_BITS> &batch_wire_value(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    int id,
    const std::bitset<BATCH_BITS> &zero,
    const std::bitset<BATCH_BITS> &one
) {
    if (id == -1) return zero;
    if (id == -2) return one;
    return bits[id];
}

void eval_one(const Netlist &nl, std::vector<uint8_t> &bits) {
    for (const Gate &g : nl.gates) {
        uint8_t y = wire_value(bits, g.ins[0]);
        switch (g.type) {
        case AND:
        case NAND:
            y = 1;
            for (int in : g.ins) y &= wire_value(bits, in);
            if (g.type == NAND) y ^= 1;
            break;
        case OR:
        case NOR:
            y = 0;
            for (int in : g.ins) y |= wire_value(bits, in);
            if (g.type == NOR) y ^= 1;
            break;
        case XOR:
        case XNOR:
            y = 0;
            for (int in : g.ins) y ^= wire_value(bits, in);
            if (g.type == XNOR) y ^= 1;
            break;
        case NOT:
            y = wire_value(bits, g.ins[0]) ^ 1;
            break;
        case BUF:
            y = wire_value(bits, g.ins[0]);
            break;
        }
        bits[g.out] = y & 1;
    }
}

void batch_set_port(
    std::vector<std::bitset<BATCH_BITS>> &bits,
    const Netlist &nl,
    const Port &p,
    size_t lane,
    uint64_t value
) {
    if (p.width == 1) {
        bits.at(nl.wire_id.at(p.name)).set(lane, value & 1);
        return;
    }
    for (int i = 0; i < p.width; ++i) {
        bits.at(nl.wire_id.at(p.name + "[" + std::to_string(i) + "]")).set(lane, (value >> i) & 1);
    }
}

uint64_t batch_get_port(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    const Netlist &nl,
    const Port &p,
    size_t lane
) {
    if (p.width == 1) return bits.at(nl.wire_id.at(p.name)).test(lane) ? 1 : 0;
    uint64_t value = 0;
    for (int i = 0; i < p.width; ++i) {
        if (bits.at(nl.wire_id.at(p.name + "[" + std::to_string(i) + "]")).test(lane)) {
            value |= uint64_t(1) << i;
        }
    }
    return value;
}

uint64_t batch_get_signal(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    const Signal &sig,
    size_t lane
) {
    uint64_t value = 0;
    size_t limit = std::min<size_t>(sig.bit_ids.size(), 64);
    for (size_t i = 0; i < limit; ++i) {
        if (bits.at(sig.bit_ids[i]).test(lane)) value |= uint64_t(1) << i;
    }
    return value;
}

std::string batch_get_signal_text(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    const Signal &sig,
    size_t lane
) {
    if (sig.bit_ids.size() <= 64) return std::to_string(batch_get_signal(bits, sig, lane));

    size_t nibbles = (sig.bit_ids.size() + 3) / 4;
    std::string hex(nibbles, '0');
    static const char *digits = "0123456789abcdef";
    for (size_t nibble = 0; nibble < nibbles; ++nibble) {
        int value = 0;
        for (size_t bit = 0; bit < 4; ++bit) {
            size_t signal_bit = nibble * 4 + bit;
            if (signal_bit < sig.bit_ids.size() && bits.at(sig.bit_ids[signal_bit]).test(lane)) {
                value |= 1 << bit;
            }
        }
        hex[nibbles - 1 - nibble] = digits[value];
    }
    size_t first = hex.find_first_not_of('0');
    if (first == std::string::npos) return "0";
    return "0x" + hex.substr(first);
}

uint64_t value_mask(int width) {
    if (width >= 64) return ~uint64_t(0);
    return (uint64_t(1) << width) - 1;
}

uint64_t batch_get_named_value(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    const Netlist &nl,
    const std::string &name,
    int width,
    size_t lane
) {
    uint64_t value = 0;
    if (width == 1) {
        auto exact = nl.wire_id.find(name);
        if (exact == nl.wire_id.end()) throw std::runtime_error("unknown signal in assign eval: " + name);
        return bits.at(exact->second).test(lane) ? 1 : 0;
    }
    for (int i = 0; i < std::min(width, 64); ++i) {
        auto it = nl.wire_id.find(name + "[" + std::to_string(i) + "]");
        if (it == nl.wire_id.end()) throw std::runtime_error("unknown vector bit in assign eval: " + name);
        if (bits.at(it->second).test(lane)) value |= uint64_t(1) << i;
    }
    return value;
}

uint64_t eval_expr_lane(
    const std::vector<std::bitset<BATCH_BITS>> &bits,
    const Netlist &nl,
    const Expr &expr,
    size_t lane
) {
    uint64_t value = 0;
    switch (expr.kind) {
    case Expr::CONST_VALUE:
        return expr.value & value_mask(expr.width);
    case Expr::SIGNAL_VALUE:
        return batch_get_named_value(bits, nl, expr.signal, expr.width, lane) & value_mask(expr.width);
    case Expr::CONCAT:
        for (const auto &arg : expr.args) {
            uint64_t part = eval_expr_lane(bits, nl, *arg, lane) & value_mask(arg->width);
            value = (value << arg->width) | part;
        }
        return value & value_mask(expr.width);
    case Expr::REPLICATE:
        if (expr.args.empty()) return 0;
        for (uint64_t i = 0; i < expr.value; ++i) {
            const Expr &arg = *expr.args[0];
            uint64_t part = eval_expr_lane(bits, nl, arg, lane) & value_mask(arg.width);
            value = (value << arg.width) | part;
        }
        return value & value_mask(expr.width);
    case Expr::TERNARY:
        return eval_expr_lane(bits, nl, *expr.args[0], lane)
            ? (eval_expr_lane(bits, nl, *expr.args[1], lane) & value_mask(expr.width))
            : (eval_expr_lane(bits, nl, *expr.args[2], lane) & value_mask(expr.width));
    case Expr::ADD:
        for (const auto &arg : expr.args) value += eval_expr_lane(bits, nl, *arg, lane);
        return value & value_mask(expr.width);
    case Expr::SUB:
        if (expr.args.empty()) return 0;
        value = eval_expr_lane(bits, nl, *expr.args[0], lane);
        for (size_t i = 1; i < expr.args.size(); ++i) value -= eval_expr_lane(bits, nl, *expr.args[i], lane);
        return value & value_mask(expr.width);
    case Expr::CAST_SIGNED: {
        if (expr.args.empty()) return 0;
        const Expr &arg = *expr.args[0];
        value = eval_expr_lane(bits, nl, arg, lane) & value_mask(arg.width);
        if (arg.width > 0 && arg.width < expr.width && arg.width < 64 && (value & (uint64_t(1) << (arg.width - 1)))) {
            value |= value_mask(expr.width) & ~value_mask(arg.width);
        }
        return value & value_mask(expr.width);
    }
    case Expr::CAST_UNSIGNED:
        if (expr.args.empty()) return 0;
        return eval_expr_lane(bits, nl, *expr.args[0], lane) & value_mask(expr.width);
    }
    return 0;
}

void batch_set_named_value(
    std::vector<std::bitset<BATCH_BITS>> &bits,
    const Netlist &nl,
    const std::string &name,
    uint64_t value,
    size_t lane
) {
    std::string lhs = trim(name);
    if (lhs.size() >= 2 && lhs.front() == '{' && lhs.back() == '}') {
        uint64_t shifted = value;
        std::vector<std::string> parts = split_top_level(lhs.substr(1, lhs.size() - 2), ',');
        for (auto it = parts.rbegin(); it != parts.rend(); ++it) {
            int width = lhs_width(nl, *it);
            batch_set_named_value(bits, nl, *it, shifted & value_mask(width), lane);
            shifted >>= width;
        }
        return;
    }
    auto width_it = nl.vector_width.find(lhs);
    if (width_it == nl.vector_width.end()) {
        auto exact = nl.wire_id.find(lhs);
        if (exact == nl.wire_id.end()) throw std::runtime_error("unknown assign lhs: " + lhs);
        bits.at(exact->second).set(lane, value & 1);
        return;
    }
    int width = width_it->second;
    if (width == 1) {
        bits.at(nl.wire_id.at(lhs)).set(lane, value & 1);
        return;
    }
    for (int i = 0; i < width; ++i) {
        bits.at(nl.wire_id.at(lhs + "[" + std::to_string(i) + "]")).set(lane, (value >> i) & 1);
    }
}

void eval_batch(
    const Netlist &nl,
    std::vector<std::bitset<BATCH_BITS>> &bits,
    size_t count
) {
    const std::bitset<BATCH_BITS> zero;
    const std::bitset<BATCH_BITS> one = ~zero;
    for (const Step &step : nl.steps) {
        if (step.is_assign) {
            const Assign &assign = nl.assigns.at(step.index);
            for (size_t lane = 0; lane < count; ++lane) {
                batch_set_named_value(bits, nl, assign.lhs, eval_expr_lane(bits, nl, *assign.rhs, lane), lane);
            }
            continue;
        }
        const Gate &g = nl.gates.at(step.index);
        std::bitset<BATCH_BITS> y;
        switch (g.type) {
        case AND:
        case NAND:
            y = one;
            for (int in : g.ins) y &= batch_wire_value(bits, in, zero, one);
            if (g.type == NAND) y = ~y;
            break;
        case OR:
        case NOR:
            y = zero;
            for (int in : g.ins) y |= batch_wire_value(bits, in, zero, one);
            if (g.type == NOR) y = ~y;
            break;
        case XOR:
        case XNOR:
            y = zero;
            for (int in : g.ins) y ^= batch_wire_value(bits, in, zero, one);
            if (g.type == XNOR) y = ~y;
            break;
        case NOT:
            y = ~batch_wire_value(bits, g.ins[0], zero, one);
            break;
        case BUF:
            y = batch_wire_value(bits, g.ins[0], zero, one);
            break;
        }
        bits[g.out] = y;
    }
}

std::unordered_map<std::string, uint64_t> parse_line_values(const Netlist &nl, const std::string &line) {
    std::unordered_map<std::string, uint64_t> values;
    std::stringstream ss(line);
    std::string tok;
    size_t positional = 0;
    while (ss >> tok) {
        size_t eq = tok.find('=');
        if (eq == std::string::npos) {
            if (positional >= nl.inputs.size()) throw std::runtime_error("too many positional inputs");
            values[nl.inputs[positional++].name] = parse_u64(tok);
        } else {
            values[tok.substr(0, eq)] = parse_u64(tok.substr(eq + 1));
        }
    }
    return values;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "usage: fast_primitive_sampler <top_primitive.v> [signal ...]\n";
        return 2;
    }
    try {
        Netlist nl = parse_netlist(argv[1]);
        bool use_all_signals = false;
        std::vector<std::string> signal_names;
        for (int i = 2; i < argc; ++i) {
            std::string arg = argv[i];
            if (arg == "--all-signals") {
                use_all_signals = true;
            } else if (arg == "--signals-file") {
                if (++i >= argc) throw std::runtime_error("--signals-file requires a path");
                std::vector<std::string> file_names = read_signal_file(argv[i]);
                signal_names.insert(signal_names.end(), file_names.begin(), file_names.end());
            } else {
                signal_names.push_back(arg);
            }
        }
        std::vector<Signal> signals;
        if (use_all_signals) {
            signals = all_wire_signals(nl);
        } else if (signal_names.empty()) {
            signals = default_output_signals(nl);
        } else {
            for (const std::string &name : signal_names) signals.push_back(resolve_signal(nl, name));
        }
        std::vector<std::unordered_map<std::string, uint64_t>> vectors;
        std::string line;
        while (std::getline(std::cin, line)) {
            line = trim(line);
            if (line.empty()) continue;
            vectors.push_back(parse_line_values(nl, line));
        }

        std::vector<std::bitset<BATCH_BITS>> bits(nl.wire_id.size());
        for (size_t base = 0; base < vectors.size(); base += BATCH_BITS) {
            size_t count = std::min(BATCH_BITS, vectors.size() - base);
            for (auto &w : bits) w.reset();
            for (size_t lane = 0; lane < count; ++lane) {
                const auto &values = vectors[base + lane];
                for (const Port &p : nl.inputs) {
                    auto it = values.find(p.name);
                    batch_set_port(bits, nl, p, lane, it == values.end() ? 0 : it->second);
                }
            }
            eval_batch(nl, bits, count);
            for (size_t lane = 0; lane < count; ++lane) {
                for (size_t i = 0; i < signals.size(); ++i) {
                    if (i) std::cout << ' ';
                    std::cout << signals[i].label << '=' << batch_get_signal_text(bits, signals[i], lane);
                }
                std::cout << '\n';
            }
        }

    } catch (const std::exception &e) {
        std::cerr << "fast_primitive_sampler: " << e.what() << '\n';
        return 1;
    }
    return 0;
}
